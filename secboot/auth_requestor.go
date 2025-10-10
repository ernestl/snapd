// -*- Mode: Go; indent-tabs-mode: t -*-
//go:build !nosecboot

/*
 * Copyright (C) 2025 Canonical Ltd
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

package secboot

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	sb "github.com/snapcore/secboot"

	"github.com/snapcore/snapd/logger"
	"github.com/snapcore/snapd/systemd"
)

type systemdAuthRequestor struct {
}

func credentialOptions(authTypes sb.UserAuthType) (string, error) {
	const knownTypes = sb.UserAuthTypePassphrase | sb.UserAuthTypePIN | sb.UserAuthTypeRecoveryKey

	if authTypes == 0 {
		return "", errors.New("user authorization type not specified")
	}

	parts := make([]string, 0, 3)
	if authTypes&sb.UserAuthTypePassphrase != 0 {
		parts = append(parts, "passphrase")
	}
	if authTypes&sb.UserAuthTypePIN != 0 {
		parts = append(parts, "PIN")
	}
	if authTypes&sb.UserAuthTypeRecoveryKey != 0 {
		parts = append(parts, "recovery key")
	}

	unknownTypesPresent := authTypes&^knownTypes != 0

	var options string
	switch len(parts) {
	case 0:
		if unknownTypesPresent {
			// only unknown type(s) present
			return "", errors.New("cannot use unknown user authorization type")
		}
	case 1:
		options = parts[0]
	case 2:
		options = parts[0] + " or " + parts[1]
	default:
		options = parts[0] + ", " + parts[1] + " or " + parts[2]
	}

	if unknownTypesPresent {
		// known and unknown type(s) present
		logger.Noticef("WARNING: detected unknown user authorization type")
	}

	return options, nil
}

func getAskPasswordMessage(authTypes sb.UserAuthType, name, path string) (string, error) {
	options, err := credentialOptions(authTypes)
	if err != nil {
		return err
	}

	return fmt.Sprintf("Enter %s for %s (%s):", options, name, path), nil
}

// RequestUserCredential implements AuthRequestor.RequestUserCredential
func (r *systemdAuthRequestor) RequestUserCredential(ctx context.Context, name, path string, authTypes sb.UserAuthType) (string, error) {
	enableCredential := true
	err := systemd.EnsureAtLeast(249)
	if systemd.IsSystemdTooOld(err) {
		enableCredential = false
	}

	var args []string

	args = append(args, "--icon", "drive-harddisk")
	args = append(args, "--id", filepath.Base(os.Args[0])+":"+path)

	if enableCredential {
		args = append(args, "--credential=snapd.fde.password")
	}

	msg, err := getAskPasswordMessage(authTypes, name, path)
	if err != nil {
		return "", err
	}
	args = append(args, msg)

	cmd := exec.CommandContext(
		ctx, "systemd-ask-password",
		args...)
	out := new(bytes.Buffer)
	cmd.Stdout = out
	cmd.Stdin = os.Stdin
	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("cannot execute systemd-ask-password: %w", err)
	}
	result, err := out.ReadString('\n')
	if err != nil {
		// The only error returned from bytes.Buffer.ReadString is io.EOF.
		return "", errors.New("systemd-ask-password output is missing terminating newline")
	}
	return strings.TrimRight(result, "\n"), nil
}

// NewSystemdAuthRequestor creates an AuthRequestor
// which calls systemd-ask-password with credential parameter.
func NewSystemdAuthRequestor() sb.AuthRequestor {
	return &systemdAuthRequestor{}
}
