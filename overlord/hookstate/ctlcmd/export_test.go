// -*- Mode: Go; indent-tabs-mode: t -*-

/*
 * Copyright (C) 2016 Canonical Ltd
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

package ctlcmd

import (
	"context"
	"errors"

	"github.com/snapcore/snapd/asserts"
	"github.com/snapcore/snapd/asserts/snapasserts"
	"github.com/snapcore/snapd/client/clientutil"
	"github.com/snapcore/snapd/confdb"
	"github.com/snapcore/snapd/osutil/user"
	"github.com/snapcore/snapd/overlord/confdbstate"
	"github.com/snapcore/snapd/overlord/devicestate"
	"github.com/snapcore/snapd/overlord/hookstate"
	"github.com/snapcore/snapd/overlord/servicestate"
	"github.com/snapcore/snapd/overlord/snapstate"
	"github.com/snapcore/snapd/overlord/state"
	"github.com/snapcore/snapd/snap"
	"github.com/snapcore/snapd/testutil"
)

const (
	NotASnapCode    = notASnapCode
	ClassicSnapCode = classicSnapCode
)

var (
	AttributesTask = attributesTask

	KmodCheckConnection = kmodCheckConnection
	KmodMatchConnection = kmodMatchConnection
)

type KmodCommand = kmodCommand

func MockKmodCheckConnection(f func(*hookstate.Context, string, []string) error) (restore func()) {
	r := testutil.Backup(&kmodCheckConnection)
	kmodCheckConnection = f
	return r
}

func MockKmodLoadModule(f func(string, []string) error) (restore func()) {
	r := testutil.Backup(&kmodLoadModule)
	kmodLoadModule = f
	return r
}

func MockKmodUnloadModule(f func(string) error) (restore func()) {
	r := testutil.Backup(&kmodUnloadModule)
	kmodUnloadModule = f
	return r
}

func MockServicestateControlFunc(f func(*state.State, []*snap.AppInfo, *servicestate.Instruction, *user.User, *servicestate.Flags, *hookstate.Context) ([]*state.TaskSet, error)) (restore func()) {
	old := servicestateControl
	servicestateControl = f
	return func() { servicestateControl = old }
}

func MockSnapstateInstallComponentsFunc(f func(ctx context.Context, st *state.State, names []string, info *snap.Info, vsets *snapasserts.ValidationSets, opts snapstate.Options) ([]*state.TaskSet, error)) (restore func()) {
	old := snapstateInstallComponents
	snapstateInstallComponents = f
	return func() { snapstateInstallComponents = old }
}

func MockSnapstateRemoveComponentsFunc(f func(st *state.State, snapName string, compName []string, opts snapstate.RemoveComponentsOpts) ([]*state.TaskSet, error)) (restore func()) {
	old := snapstateRemoveComponents
	snapstateRemoveComponents = f
	return func() { snapstateRemoveComponents = old }
}

func MockDevicestateSystemModeInfoFromState(f func(*state.State) (*devicestate.SystemModeInfo, error)) (restore func()) {
	old := devicestateSystemModeInfoFromState
	devicestateSystemModeInfoFromState = f
	return func() { devicestateSystemModeInfoFromState = old }
}

func AddMockCommand(name string) *MockCommand {
	return addMockCmd(name, false)
}

func AddHiddenMockCommand(name string) *MockCommand {
	return addMockCmd(name, true)
}

func addMockCmd(name string, hidden bool) *MockCommand {
	mockCommand := NewMockCommand()
	cmd := addCommand(name, "", "", func() command { return mockCommand })
	cmd.hidden = hidden
	return mockCommand
}

func RemoveCommand(name string) {
	delete(commands, name)
}

func FormatLongPublisher(snapInfo *snap.Info, storeAccountID string) string {
	var mf modelCommandFormatter

	mf.snapInfo = snapInfo
	return mf.LongPublisher(storeAccountID)
}

func FindSerialAssertion(st *state.State, modelAssertion *asserts.Model) (*asserts.Serial, error) {
	var mc modelCommand
	return mc.findSerialAssertion(st, modelAssertion)
}

type MockCommand struct {
	baseCommand

	ExecuteError bool
	FakeStdout   string
	FakeStderr   string

	Args []string
}

func NewMockCommand() *MockCommand {
	return &MockCommand{
		ExecuteError: false,
	}
}

func (c *MockCommand) Execute(args []string) error {
	c.Args = args

	if c.FakeStdout != "" {
		c.print(c.FakeStdout)
	}

	if c.FakeStderr != "" {
		c.error(c.FakeStderr)
	}

	if c.ExecuteError {
		return errors.New("failed at user request")
	}

	return nil
}

func MockCgroupSnapNameFromPid(f func(int) (string, error)) (restore func()) {
	old := cgroupSnapNameFromPid
	cgroupSnapNameFromPid = f
	return func() {
		cgroupSnapNameFromPid = old
	}
}

func MockAutoRefreshForGatingSnap(f func(st *state.State, gatingSnap string) error) (restore func()) {
	old := autoRefreshForGatingSnap
	autoRefreshForGatingSnap = f
	return func() {
		autoRefreshForGatingSnap = old
	}
}

func MockNewStatusDecorator(f func(ctx context.Context, isGlobal bool, uid string) clientutil.StatusDecorator) (restore func()) {
	restore = testutil.Backup(&newStatusDecorator)
	newStatusDecorator = f
	return restore
}

func MockConfdbstateTransactionForSet(f func(*hookstate.Context, *state.State, *confdb.View) (*confdbstate.Transaction, confdbstate.CommitTxFunc, error)) (restore func()) {
	old := confdbstateTransactionForSet
	confdbstateTransactionForSet = f
	return func() {
		confdbstateTransactionForSet = old
	}
}

func MockConfdbstateGetView(f func(st *state.State, account, confdbName, viewName string) (*confdb.View, error)) (restore func()) {
	old := confdbstateGetView
	confdbstateGetView = f
	return func() {
		confdbstateGetView = old
	}
}

func MockConfdbstateTransactionForGet(f func(*hookstate.Context, *confdb.View, []string) (*confdbstate.Transaction, error)) (restore func()) {
	old := confdbstateTransactionForGet
	confdbstateTransactionForGet = f
	return func() {
		confdbstateTransactionForGet = old
	}
}
