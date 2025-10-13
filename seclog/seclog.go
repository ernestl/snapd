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
	"fmt"
	"io"
	"os"
	"sync"
	//"gopkg.in/natefinch/lumberjack.v2"
)

var (
	providers           = map[Impl]Provider{}
	globalLogger Logger = newNopLogger()
	lock         sync.Mutex
)

// Logger provides security logging.
type Logger interface {
	LogLoginSuccess(user string)
	LogLoginFailure(user string)
}

// Level is the importance or severity of a log event.
// The higher the level, the more severe the event.
type Level int

// Log levels.
const (
	LevelDebug    Level = 1
	LevelInfo     Level = 2
	LevelWarn     Level = 3
	LevelError    Level = 4
	LevelCritical Level = 5
)

// String returns a name for the level.
// If the level has a name, then that name
// in uppercase is returned.
// If the level is between named values, then
// an integer is appended to the uppercased name.
// Examples:
//
//	LevelWarn.String() => "WARN"
//	(LevelCritical+2).String() => "CRITICAL+2"
func (l Level) String() string {
	str := func(base string, val Level) string {
		if val == 0 {
			return base
		}
		return fmt.Sprintf("%s%+d", base, val)
	}

	switch {
	case l < LevelInfo:
		return str("DEBUG", l-LevelDebug)
	case l < LevelWarn:
		return str("INFO", l-LevelInfo)
	case l < LevelError:
		return str("WARN", l-LevelWarn)
	case l < LevelCritical:
		return str("ERROR", l-LevelError)
	default:
		return str("CRITICAL", l-LevelCritical)
	}
}

// Impl represent a known logger implementation.
type Impl string

// Logger implementations.
const (
	ImplNop  Impl = "nop"
	ImplSlog Impl = "slog" // slog based structured logger
)

// Provider provides functions required for contructing a [Logger].
// It is intended for registration of available loggers.
type Provider interface {
	New(writer io.Writer, appID string, level Level) Logger
	Impl() Impl
}

// Register makes a provider available by name.
// Should be called from init().
func Register(provider Provider) {
	lock.Lock()
	defer lock.Unlock()
	impl := provider.Impl()
	if _, exists := providers[impl]; exists {
		panic("attempting registration for existing logger " + impl)
	}
	providers[impl] = provider
}

// Setup sets a new global logger.
func SetupLogger(impl Impl, appID string, level Level) {
	lock.Lock()
	defer lock.Unlock()
	if provider, exists := providers[impl]; exists {
		setLogger(provider.New(os.Stdout, appID, level))
	}
}

func setLogger(l Logger) {
	lock.Lock()
	defer lock.Unlock()
	globalLogger = l
}

// LogLoginSuccess using the current global security logger.
func LogLoginSuccess(user string) {
	lock.Lock()
	defer lock.Unlock()
	globalLogger.LogLoginSuccess(user)
}

// LogLoginFailure using the current global security logger.
func LogLoginFailure(user string) {
	lock.Lock()
	defer lock.Unlock()
	globalLogger.LogLoginFailure(user)
}
