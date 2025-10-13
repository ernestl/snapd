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

// Ensure [NoopLogger] implements [Logger].
var _ Logger = (*NoopLogger)(nil)

// Noop logger provides a noop logger implementation.
type NoopLogger struct{}

// LogLoginSuccess implements [Logger.LogLoginSuccess].
func (NoopLogger) LogLoginSuccess(user string) {
}

// LogLoginFailure implements [Logger.LogLoginFailure].
func (NoopLogger) LogLoginFailure(user string) {
}

// NewNoopLogger returns a new [NoopLogger]. Parameters are accepted for
// API parity, but ignored.
func NewNoopLogger(_ io.Writer, _ string, _ Level) Logger {
	logger := &NoopLogger{}
	return logger
}
