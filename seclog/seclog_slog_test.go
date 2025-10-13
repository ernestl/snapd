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

package seclog_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	. "gopkg.in/check.v1"
	"log/slog"

	"github.com/snapcore/snapd/seclog"
	"github.com/snapcore/snapd/testutil"
)

type SecLogSlogSuite struct {
	testutil.BaseTest
	buf   *bytes.Buffer
	appId string
}

var _ = Suite(&SecLogSlogSuite{})

func TestSecLog(t *testing.T) { TestingT(t) }

func (s *SecLogSlogSuite) SetUpSuite(c *C) {
	s.buf = &bytes.Buffer{}
	s.appId = "canonical.snapd"
}

func (s *SecLogSlogSuite) SetUpTest(c *C) {
	s.BaseTest.SetUpTest(c)
	s.buf.Reset()
}

func (s *SecLogSlogSuite) TearDownTest(c *C) {
}

// extractSlogLogger is a test helper to extract the internal [slog.Logger] from
// Logger.
func extractSlogLogger(logger seclog.Logger) (*slog.Logger, error) {
	if l, ok := logger.(*seclog.SlogLogger); !ok {
		return nil, errors.New("cannot extract slog logger")
	} else {
		// return the internal slog logger
		return l.Logger(), nil
	}
}

func (s *SecLogSlogSuite) TestNew(c *C) {
	buf := &bytes.Buffer{}
	logger := seclog.NewSlogLogger(buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)
}

// builtinAttrs represents the non-optional attributes that is present in
// every record
type builtinAttrs struct {
	Datetime    time.Time `json:"datetime"`
	Level       string    `json:"level"`
	Description string    `json:"description"`
	AppID       string    `json:"appid"`
}

func (s *SecLogSlogSuite) TestHandlerAttrsAllTypes(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type AttrsAllTypes struct {
		builtinAttrs
		String    string        `json:"string"`
		Duration  time.Duration `json:"duration"`
		Timestamp time.Time     `json:"timestamp"`
		Float64   float64       `json:"float64"`
		Int64     int64         `json:"int64"`
		Int       int           `json:"int"`
		Uint64    uint64        `json:"uint64"`
		Any       any           `json:"any"`
	}

	sl, err := extractSlogLogger(logger)
	c.Assert(err, IsNil)
	sl.LogAttrs(
		context.Background(),
		slog.Level(seclog.LevelInfo),
		"test description",
		slog.Attr{"string", slog.StringValue("test string")},
		slog.Attr{"duration", slog.DurationValue(time.Duration(90 * time.Second))},
		slog.Attr{
			"timestamp",
			slog.TimeValue(time.Date(2025, 10, 8, 8, 0, 0, 0, time.UTC)),
		},
		slog.Attr{"float64", slog.Float64Value(3.141592653589793)},
		slog.Attr{"int64", slog.Int64Value(-4611686018427387904)},
		slog.Attr{"int", slog.IntValue(-4294967296)},
		slog.Attr{"uint64", slog.Uint64Value(4294967295)},
		// AnyValue returns value of KindInt64, the original
		// numeric type is not preserved
		slog.Attr{"any", slog.AnyValue(map[string]any{"k": "v", "n": int(1)})},
	)

	var obtained AttrsAllTypes
	err = json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)

	c.Check(time.Now().Sub(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "INFO")
	c.Check(obtained.Description, Equals, "test description")
	c.Check(obtained.AppID, Equals, s.appId)
	c.Check(obtained.String, Equals, "test string")
	c.Check(obtained.Duration, Equals, time.Duration(90*time.Second))
	c.Check(obtained.Timestamp, Equals, time.Date(2025, 10, 8, 8, 0, 0, 0, time.UTC))
	c.Check(obtained.Float64, Equals, float64(3.141592653589793))
	c.Check(obtained.Int64, Equals, int64(-4611686018427387904))
	c.Check(obtained.Int, Equals, int(-4294967296))
	c.Check(obtained.Uint64, Equals, uint64(4294967295))
	c.Check(obtained.Any, DeepEquals, map[string]any{"k": "v", "n": float64(1)})
}

func (s *SecLogSlogSuite) TestLogLoginSuccess(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type LoginSuccess struct {
		builtinAttrs
		Event string `json:"event"`
		User  string `json:"user"`
	}

	logger.LogLoginSuccess("user@gmail.com")

	var obtained LoginSuccess
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Now().Sub(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "INFO")
	c.Check(obtained.Description, Equals, "User user@gmail.com login success")
	c.Check(obtained.AppID, Equals, s.appId)
	c.Check(obtained.Event, Equals, "authn_login_success")
	c.Check(obtained.User, Equals, "user@gmail.com")
}

func (s *SecLogSlogSuite) TestLogLoginFailure(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type loginFailure struct {
		builtinAttrs
		Event string `json:"event"`
		User  string `json:"user"`
	}

	logger.LogLoginFailure("user@gmail.com")

	var obtained loginFailure
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Now().Sub(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "WARN")
	c.Check(obtained.Description, Equals, "User user@gmail.com login failure")
	c.Check(obtained.AppID, Equals, s.appId)
	c.Check(obtained.Event, Equals, "authn_login_failure")
	c.Check(obtained.User, Equals, "user@gmail.com")
}
