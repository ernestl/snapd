// -*- Mode: Go; indent-tabs-mode: t -*-

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

package seclog

import (
	"io"
)

// Ensure [NopLogger] implements [Logger].
var _ Logger = (*NopLogger)(nil)

// Nop logger provides a no-operation [Logger] implementation.
type NopLogger struct{}

// LogLoginSuccess implements [Logger.LogLoginSuccess].
func (NopLogger) LogLoginSuccess(user string) {
}

// LogLoginFailure implements [Logger.LogLoginFailure].
func (NopLogger) LogLoginFailure(user string) {
}

// NewNopLogger returns a new [NopLogger].
func NewNopLogger() Logger {
	logger := &NopLogger{}
	return logger
}

// nopProvider implements [Provider]
type nopProvider struct{}

// New returns a nop [Logger].
// Params are ignored.
func (nopProvider) New(_ io.Writer, _ string, _ Level) Logger {
	return NopLogger{}
}

// Impl returns the implementation.
func (nopProvider) Impl() Impl {
	return Nop
}

func init() {
	Register(nopProvider{})
}
