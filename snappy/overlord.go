// -*- Mode: Go; indent-tabs-mode: t -*-

/*
 * Copyright (C) 2014-2016 Canonical Ltd
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 3 as
 * published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 */

package snappy

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/ubuntu-core/snappy/arch"
	"github.com/ubuntu-core/snappy/dirs"
	"github.com/ubuntu-core/snappy/logger"
	"github.com/ubuntu-core/snappy/progress"
	"github.com/ubuntu-core/snappy/snap"
	"github.com/ubuntu-core/snappy/snap/squashfs"
)

// Overlord is responsible for the overall system state.
type Overlord struct {
}

// CheckSnap ensures that the snap can be installed
func CheckSnap(snapFilePath, developer string, flags InstallFlags, meter progress.Meter) error {
	allowGadget := (flags & AllowGadget) != 0
	allowUnauth := (flags & AllowUnauthenticated) != 0

	// warning: NewSnapFile generates a new sideloaded version
	//          everytime it is run.
	//          so all paths on disk are different even if the same snap
	s, err := NewSnapFile(snapFilePath, developer, allowUnauth)
	if err != nil {
		return err
	}

	// we do not security Verify() (check hashes) the package here.
	// This is done earlier in
	// NewSnapFile() to ensure that we do not mount/inspect
	// potentially dangerous snaps
	return canInstall(s, allowGadget, meter)
}

// SetupSnap does prepare and mount the snap for further processing
// It returns the installed path and an error
func SetupSnap(snapFilePath, developer string, flags InstallFlags, meter progress.Meter) (string, error) {
	inhibitHooks := (flags & InhibitHooks) != 0
	allowUnauth := (flags & AllowUnauthenticated) != 0

	// warning: NewSnapFile generates a new sideloaded version
	//          everytime it is run
	//          so all paths on disk are different even if the same snap
	s, err := NewSnapFile(snapFilePath, developer, allowUnauth)
	if err != nil {
		return s.instdir, err
	}

	// the "gadget" snaps are special
	if s.Type() == snap.TypeGadget {
		if err := installGadgetHardwareUdevRules(s.m); err != nil {
			return s.instdir, err
		}
	}

	if err := os.MkdirAll(s.instdir, 0755); err != nil {
		logger.Noticef("Can not create %q: %v", s.instdir, err)
		return s.instdir, err
	}

	if err := s.deb.Install(s.instdir); err != nil {
		return s.instdir, err
	}

	// generate the mount unit for the squashfs
	if err := addSquashfsMount(s.m, s.instdir, inhibitHooks, meter); err != nil {
		return s.instdir, err
	}

	// FIXME: special handling is bad 'mkay
	if s.m.Type == snap.TypeKernel {
		if err := extractKernelAssets(s, meter, flags); err != nil {
			return s.instdir, fmt.Errorf("failed to install kernel %s", err)
		}
	}

	return s.instdir, err
}

func UndoSetupSnap(installDir, developer string, meter progress.Meter) {
	if s, err := NewInstalledSnap(filepath.Join(installDir, "meta", "snap.yaml"), developer); err == nil {
		if err := removeSquashfsMount(s.m, s.basedir, meter); err != nil {
			fullName := QualifiedName(s.Info())
			logger.Noticef("Failed to remove mount unit for  %s: %s", fullName, err)
		}
	}
	if err := os.RemoveAll(installDir); err != nil && !os.IsNotExist(err) {
		logger.Noticef("Failed to remove %q: %v", installDir, err)
	}

	// FIXME: undo extract kernel assets via removeKernelAssets
	//
	// FIXME2: undo installGadgetHardwareUdevRules via
	//         cleanupGadgetHardwareUdevRules
}

// Install installs the given snap file to the system.
//
// It returns the local snap file or an error
func (o *Overlord) Install(snapFilePath string, developer string, flags InstallFlags, meter progress.Meter) (sp *Snap, err error) {
	inhibitHooks := (flags & InhibitHooks) != 0

	// we do not Verify() the package here. This is done earlier in
	// NewSnapFile() to ensure that we do not mount/inspect
	// potentially dangerous snaps
	if err := CheckSnap(snapFilePath, developer, flags, meter); err != nil {
		return nil, err
	}

	// prepare the snap for further processing
	instPath, err := SetupSnap(snapFilePath, developer, flags, meter)
	defer func() {
		if err != nil {
			UndoSetupSnap(instPath, developer, meter)
		}
	}()
	if err != nil {
		return nil, err
	}

	// we have a installed snap at this point
	newSnap, err := NewInstalledSnap(filepath.Join(instPath, "meta", "snap.yaml"), developer)
	if err != nil {
		return nil, err
	}

	fullName := QualifiedName(newSnap.Info())
	dataDir := filepath.Join(dirs.SnapDataDir, fullName, newSnap.Version())

	var oldSnap *Snap
	if currentActiveDir, _ := filepath.EvalSymlinks(filepath.Join(newSnap.basedir, "..", "current")); currentActiveDir != "" {
		oldSnap, err = NewInstalledSnap(filepath.Join(currentActiveDir, "meta", "snap.yaml"), newSnap.developer)
		if err != nil {
			return nil, err
		}
	}

	// deal with the data:
	//
	// if there was a previous version, stop it
	// from being active so that it stops running and can no longer be
	// started then copy the data
	//
	// otherwise just create a empty data dir
	if oldSnap != nil {
		// we need to stop making it active
		err = oldSnap.deactivate(inhibitHooks, meter)
		defer func() {
			if err != nil {
				if cerr := oldSnap.activate(inhibitHooks, meter); cerr != nil {
					logger.Noticef("Setting old version back to active failed: %v", cerr)
				}
			}
		}()
		if err != nil {
			return nil, err
		}

		err = copySnapData(fullName, oldSnap.Version(), newSnap.Version())
	} else {
		err = os.MkdirAll(dataDir, 0755)
	}

	defer func() {
		if err != nil {
			if cerr := removeSnapData(fullName, newSnap.Version()); cerr != nil {
				logger.Noticef("When cleaning up data for %s %s: %v", newSnap.Name(), newSnap.Version(), cerr)
			}
		}
	}()

	if err != nil {
		return nil, err
	}

	if !inhibitHooks {
		// and finally make active
		err = newSnap.activate(inhibitHooks, meter)
		defer func() {
			if err != nil && oldSnap != nil {
				if cerr := oldSnap.activate(inhibitHooks, meter); cerr != nil {
					logger.Noticef("When setting old %s version back to active: %v", newSnap.Name(), cerr)
				}
			}
		}()
		if err != nil {
			return nil, err
		}
	}

	return newSnap, nil
}

// CanInstall checks whether the Snap passes a series of tests required for installation
func canInstall(s *SnapFile, allowGadget bool, inter interacter) error {
	if err := checkForPackageInstalled(s.m, s.Developer()); err != nil {
		return err
	}

	// verify we have a valid architecture
	if !arch.IsSupportedArchitecture(s.m.Architectures) {
		return &ErrArchitectureNotSupported{s.m.Architectures}
	}

	if s.Type() == snap.TypeGadget {
		if !allowGadget {
			if currentGadget, err := getGadget(); err == nil {
				if currentGadget.Name != s.Name() {
					return ErrGadgetPackageInstall
				}
			} else {
				// there should always be a gadget package now
				return ErrGadgetPackageInstall
			}
		}
	}

	curr, _ := filepath.EvalSymlinks(filepath.Join(s.instdir, "..", "current"))
	if err := checkLicenseAgreement(s.m, inter, s.deb, curr); err != nil {
		return err
	}

	return nil
}

// Uninstall removes the given local snap from the system.
//
// It returns an error on failure
func (o *Overlord) Uninstall(s *Snap, meter progress.Meter) error {
	// Gadget snaps should not be removed as they are a key
	// building block for Gadgets. Prunning non active ones
	// is acceptible.
	if s.m.Type == snap.TypeGadget && s.IsActive() {
		return ErrPackageNotRemovable
	}

	// You never want to remove an active kernel or OS
	if (s.m.Type == snap.TypeKernel || s.m.Type == snap.TypeOS) && s.IsActive() {
		return ErrPackageNotRemovable
	}

	if IsBuiltInSoftware(s.Name()) && s.IsActive() {
		return ErrPackageNotRemovable
	}

	if err := s.deactivate(false, meter); err != nil && err != ErrSnapNotActive {
		return err
	}

	// ensure mount unit stops
	if err := removeSquashfsMount(s.m, s.basedir, meter); err != nil {
		return err
	}

	if err := os.RemoveAll(s.basedir); err != nil {
		return err
	}

	// best effort(?)
	os.Remove(filepath.Dir(s.basedir))

	// remove the snap
	if err := os.RemoveAll(squashfs.BlobPath(s.basedir)); err != nil {
		return err
	}

	// remove the kernel assets (if any)
	if s.m.Type == snap.TypeKernel {
		if err := removeKernelAssets(s, meter); err != nil {
			logger.Noticef("removing kernel assets failed with %s", err)
		}
	}

	return RemoveAllHWAccess(QualifiedName(s.Info()))
}

// SetActive sets the active state of the given snap
//
// It returns an error on failure
func (o *Overlord) SetActive(s *Snap, active bool, meter progress.Meter) error {
	if active {
		return s.activate(false, meter)
	}

	return s.deactivate(false, meter)
}

// Configure configures the given snap
//
// It returns an error on failure
func (o *Overlord) Configure(s *Snap, configuration []byte) ([]byte, error) {
	if s.m.Type == snap.TypeOS {
		return coreConfig(configuration)
	}

	return snapConfig(s.basedir, s.developer, configuration)
}

// Installed returns the installed snaps from this repository
func (o *Overlord) Installed() ([]*Snap, error) {
	globExpr := filepath.Join(dirs.SnapSnapsDir, "*", "*", "meta", "snap.yaml")
	snaps, err := o.snapsForGlobExpr(globExpr)
	if err != nil {
		return nil, fmt.Errorf("Can not get the installed snaps: %s", err)

	}

	return snaps, nil
}

func (o *Overlord) snapsForGlobExpr(globExpr string) (snaps []*Snap, err error) {
	matches, err := filepath.Glob(globExpr)
	if err != nil {
		return nil, err
	}

	for _, yamlfile := range matches {
		// skip "current" and similar symlinks
		realpath, err := filepath.EvalSymlinks(yamlfile)
		if err != nil {
			return nil, err
		}
		if realpath != yamlfile {
			continue
		}

		developer, _ := developerFromYamlPath(realpath)
		snap, err := NewInstalledSnap(realpath, developer)
		if err != nil {
			return nil, err
		}
		snaps = append(snaps, snap)
	}

	return snaps, nil
}
