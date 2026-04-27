// -*- Mode: Go; indent-tabs-mode: t -*-
//go:build go1.21 && !noslog

/*
 * Copyright (C) 2026 Canonical Ltd
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
	"encoding/json"
	"testing"

	. "gopkg.in/check.v1"

	"github.com/snapcore/snapd/logger"
	"github.com/snapcore/snapd/seclog"
	"github.com/snapcore/snapd/testutil"
)

type SecLogSuite struct {
	testutil.BaseTest
	buf   *bytes.Buffer
	appID string
}

var _ = Suite(&SecLogSuite{})

func TestSecLog(t *testing.T) { TestingT(t) }

func (s *SecLogSuite) SetUpSuite(c *C) {
	s.buf = &bytes.Buffer{}
	s.appID = "canonical.snapd"
}

func (s *SecLogSuite) SetUpTest(c *C) {
	s.BaseTest.SetUpTest(c)
	s.buf.Reset()
}

func (s *SecLogSuite) TearDownTest(c *C) {
	s.BaseTest.TearDownTest(c)
}

func (s *SecLogSuite) TestString(c *C) {
	levels := []seclog.Level{
		seclog.LevelDebug - 1,
		seclog.LevelDebug,
		seclog.LevelInfo,
		seclog.LevelWarn,
		seclog.LevelError,
		seclog.LevelError + 1,
		seclog.LevelCritical,
		seclog.LevelCritical + 2,
	}

	expected := []string{
		"DEBUG-1",
		"DEBUG",
		"INFO",
		"WARN",
		"ERROR",
		"CRITICAL",
		"CRITICAL",
		"CRITICAL+2",
	}

	c.Assert(len(levels), Equals, len(expected))

	obtained := make([]string, 0, len(levels))

	for _, level := range levels {
		obtained = append(obtained, level.String())
	}

	c.Assert(expected, DeepEquals, obtained)
}

func (s *SecLogSuite) TestSnapdUserString(c *C) {
	// All fields set.
	c.Check(seclog.SnapdUser{
		ID: 42, StoreUserEmail: "a@b.com", StoreUserName: "jdoe",
	}.String(), Equals, "42:a@b.com:jdoe")

	// All fields zero/empty — all "unknown".
	c.Check(seclog.SnapdUser{}.String(), Equals, "unknown:unknown:unknown")

	// Only ID set.
	c.Check(seclog.SnapdUser{ID: 7}.String(), Equals, "7:unknown:unknown")

	// Only email set.
	c.Check(seclog.SnapdUser{StoreUserEmail: "x@y.z"}.String(), Equals, "unknown:x@y.z:unknown")

	// Only username set.
	c.Check(seclog.SnapdUser{StoreUserName: "root"}.String(), Equals, "unknown:unknown:root")
}

func (s *SecLogSuite) TestReasonString(c *C) {
	// Both fields set.
	c.Check(seclog.Reason{
		Code: seclog.ReasonInvalidCredentials, Message: "bad password",
	}.String(), Equals, "invalid-credentials:bad password")

	// Both fields empty — all "unknown".
	c.Check(seclog.Reason{}.String(), Equals, "unknown:unknown")

	// Only code set.
	c.Check(seclog.Reason{Code: seclog.ReasonInternal}.String(), Equals, "internal:unknown")

	// Only message set.
	c.Check(seclog.Reason{Message: "something broke"}.String(), Equals, "unknown:something broke")
}

func (s *SecLogSuite) TestSetupSuccess(c *C) {
	s.setupSlogLogger(c)

	seclog.LogLoginSuccess(seclog.SnapdUser{ID: 1, StoreUserName: "testuser"})
	c.Check(s.buf.Len() > 0, Equals, true)
}

func (s *SecLogSuite) setupSlogLogger(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	seclog.Setup(logger)
}

func (s *SecLogSuite) TestLogLoginSuccess(c *C) {
	s.setupSlogLogger(c)

	user := seclog.SnapdUser{
		ID:             42,
		StoreUserEmail: "user@example.com",
		StoreUserName:  "jdoe",
	}
	seclog.LogLoginSuccess(user)

	var obtained map[string]any
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(obtained["level"], Equals, "INFO")
	c.Check(obtained["description"], Equals,
		"User 42:user@example.com:jdoe login success")
	c.Check(obtained["app_id"], Equals, s.appID)
	c.Check(obtained["category"], Equals, "AUTHN")
	c.Check(obtained["event"], Equals, "authn_login_success")
	userMap, ok := obtained["user"].(map[string]any)
	c.Assert(ok, Equals, true)
	c.Check(userMap["snapd-user-id"], Equals, float64(42))
	c.Check(userMap["store-user-email"], Equals, "user@example.com")
	c.Check(userMap["store-user-name"], Equals, "jdoe")
	c.Check(obtained["type"], Equals, "security")
}

func (s *SecLogSuite) TestLogLoginFailure(c *C) {
	s.setupSlogLogger(c)

	user := seclog.SnapdUser{
		ID:             42,
		StoreUserEmail: "user@example.com",
		StoreUserName:  "jdoe",
	}
	seclog.LogLoginFailure(user, seclog.Reason{Code: seclog.ReasonInvalidCredentials, Message: "invalid credentials"})

	var obtained map[string]any
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(obtained["level"], Equals, "WARN")
	c.Check(obtained["description"], Equals,
		"User 42:user@example.com:jdoe login failure: invalid-credentials:invalid credentials")
	c.Check(obtained["app_id"], Equals, s.appID)
	c.Check(obtained["category"], Equals, "AUTHN")
	c.Check(obtained["event"], Equals, "authn_login_failure")
	userMap, ok := obtained["user"].(map[string]any)
	c.Assert(ok, Equals, true)
	c.Check(userMap["snapd-user-id"], Equals, float64(42))
	c.Check(userMap["store-user-email"], Equals, "user@example.com")
	c.Check(userMap["store-user-name"], Equals, "jdoe")
	errMap, ok := obtained["error"].(map[string]any)
	c.Assert(ok, Equals, true)
	c.Check(errMap["code"], Equals, seclog.ReasonInvalidCredentials)
	c.Check(errMap["message"], Equals, "invalid credentials")
	c.Check(obtained["type"], Equals, "security")
}

func (s *SecLogSuite) TestLogLoggerEnabledLogsEvent(c *C) {
	s.setupSlogLogger(c)

	seclog.LogLoggerEnabled()

	var obtained map[string]any
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(obtained["level"], Equals, "INFO")
	c.Check(obtained["description"], Equals, "Security logging enabled")
	c.Check(obtained["category"], Equals, "SYS")
	c.Check(obtained["event"], Equals, "sys_logging_enabled")
}

func (s *SecLogSuite) TestLogLoggerEnabledLogsToStandardLogger(c *C) {
	s.setupSlogLogger(c)

	logBuf, restoreStdLogger := logger.MockLogger()
	defer restoreStdLogger()

	seclog.LogLoggerEnabled()

	c.Check(logBuf.String(), testutil.Contains, "security logger enabled")
}

func (s *SecLogSuite) TestLogLoggerDisabledLogsEvent(c *C) {
	s.setupSlogLogger(c)

	seclog.LogLoggerDisabled()

	var obtained map[string]any
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(obtained["level"], Equals, "CRITICAL")
	c.Check(obtained["description"], Equals, "Security logging disabled")
	c.Check(obtained["category"], Equals, "SYS")
	c.Check(obtained["event"], Equals, "sys_logging_disabled")
}

func (s *SecLogSuite) TestLogLoggerDisabledLogsToStandardLogger(c *C) {
	s.setupSlogLogger(c)

	logBuf, restoreStdLogger := logger.MockLogger()
	defer restoreStdLogger()

	seclog.LogLoggerDisabled()

	c.Check(logBuf.String(), testutil.Contains, "security logger disabled")
}
