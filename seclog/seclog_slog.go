// -*- Mode: Go; indent-tabs-mode: t -*-
//go:build go1.21 && !noslog

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
	"context"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/snapcore/snapd/osutil"
)

// Ensure [SlogLogger] implements [Logger].
var _ Logger = (*SlogLogger)(nil)

// SlogLogger provides a security specific logger based on slog.
type SlogLogger struct {
	logger   *slog.Logger
	levelVar *slog.LevelVar
	ctx      context.Context
}

// Logger is a test only helper to retrieve a pointer to the underlying
// [slog.Logger].
func (l *SlogLogger) Logger() *slog.Logger {
	osutil.MustBeTestBinary("SlogLogger should only be used in tests")
	return l.logger
}

// LogLoginSuccess implements [Logger.LogLoginSuccess].
func (l *SlogLogger) LogLoginSuccess(user string) {
	desc := fmt.Sprintf("User %s login success", user)
	l.logger.LogAttrs(
		l.ctx,
		slog.Level(LevelInfo),
		desc,
		slog.Attr{"event", slog.StringValue("authn_login_success")},
		slog.Attr{"user", slog.StringValue(user)},
	)
}

// LogLoginFailure implements [Logger.LogLoginFailure].
func (l *SlogLogger) LogLoginFailure(user string) {
	desc := fmt.Sprintf("User %s login failure", user)
	l.logger.LogAttrs(
		l.ctx,
		slog.Level(LevelWarn),
		desc,
		slog.Attr{"event", slog.StringValue("authn_login_failure")},
		slog.Attr{"user", slog.StringValue(user)},
	)
}

// newJsonHandler returns a slog JSON handler configured for security logs.
//
// It writes newline-delimited JSON to writer and enforces a schema for the
// built-in attributes:
//   - time:     key "datetime", formatted in UTC using [time.RFC3339Nano]
//   - level:    rendered as a string via levelName
//   - message:  key "description"
//   - source:   omitted
//
// Invalid built-in attribute values will be replaced with string attrInvalid.
// Additional attributes are preserved verbatim, including nested groups. The
// handler logs at or above the package-level `level` threshold. It does not
// close or sync writer.
func newJsonHandler(writer io.Writer, level slog.Leveler) slog.Handler {
	options := &slog.HandlerOptions{
		Level: level,
		ReplaceAttr: func(groups []string, attr slog.Attr) slog.Attr {
			switch attr.Key {
			case slog.TimeKey:
				// use "datetime" instead of default "time"
				attr.Key = "datetime"
				if t, ok := attr.Value.Any().(time.Time); ok {
					// convert to formatted string
					attr.Value = slog.StringValue(t.UTC().Format(time.RFC3339Nano))
				}
			case slog.LevelKey:
				if l, ok := attr.Value.Any().(slog.Level); ok {
					attr.Value = slog.StringValue(Level(l).String())
				}
			case slog.MessageKey:
				// use "description" instead of default "msg"
				attr.Key = "description"
			case slog.SourceKey:
				// drop source
				return slog.Attr{}
			}
			return attr
		},
	}

	return slog.NewJSONHandler(writer, options)
}

// NewSlogLogger constructs a security specific [Logger] backed by [slog] that
// emits structured JSON to the provided [io.Writer]. The returned logger
// enables dynamic level control via an internal [slog.LevelVar].
func NewSlogLogger(writer io.Writer, appID string, level Level) Logger {
	levelVar := new(slog.LevelVar)
	levelVar.Set(slog.Level(level))
	handler := newJsonHandler(writer, levelVar)
	logger := &SlogLogger{
		// enable dynamic level adjustment
		levelVar: levelVar,
		// always include appid
		logger: slog.New(handler).With("appid", appID),
	}
	return logger
}
