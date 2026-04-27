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
	"errors"
	"time"

	. "gopkg.in/check.v1"

	"github.com/snapcore/snapd/seclog"
	"github.com/snapcore/snapd/testutil"
)

type SlogSuite struct {
	testutil.BaseTest
	buf   *bytes.Buffer
	appID string
}

var _ = Suite(&SlogSuite{})

func (s *SlogSuite) SetUpSuite(c *C) {
	s.buf = &bytes.Buffer{}
	s.appID = "canonical.snapd"
}

func (s *SlogSuite) SetUpTest(c *C) {
	s.BaseTest.SetUpTest(c)
	s.buf.Reset()
}

func (s *SlogSuite) TearDownTest(c *C) {
	s.BaseTest.TearDownTest(c)
}

func (s *SlogSuite) TestNewSlogLogger(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Check(logger, NotNil)
}

// baseAttrs represents the non-optional attributes that is present in
// every record
type baseAttrs struct {
	Datetime    time.Time `json:"datetime"`
	Level       string    `json:"level"`
	Description string    `json:"description"`
	AppID       string    `json:"app_id"`
	Type        string    `json:"type"`
	Category    string    `json:"category"`
}

// orderedKeys extracts the top-level JSON object keys in order.
func orderedKeys(data []byte) ([]string, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	// consume opening '{'
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	if delim, ok := token.(json.Delim); !ok || delim != '{' {
		return nil, errors.New("expected '{' delimiter")
	}
	var keys []string
	for decoder.More() {
		token, err = decoder.Token()
		if err != nil {
			return nil, err
		}
		key, ok := token.(string)
		if !ok {
			return nil, errors.New("expected string key")
		}
		keys = append(keys, key)
		// skip value
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return nil, err
		}
	}
	return keys, nil
}

func (s *SlogSuite) TestLogLoggerEnabled(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type sysEvent struct {
		baseAttrs
		Event string `json:"event"`
	}

	logger.LogLoggerEnabled()

	var obtained sysEvent
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Since(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "INFO")
	c.Check(obtained.Description, Equals, "Security logging enabled")
	c.Check(obtained.AppID, Equals, s.appID)
	c.Check(obtained.Type, Equals, "security")
	c.Check(obtained.Category, Equals, "SYS")
	c.Check(obtained.Event, Equals, "sys_logging_enabled")

	// verify key order for human readability
	keys, err := orderedKeys(s.buf.Bytes())
	c.Assert(err, IsNil)
	c.Check(keys, DeepEquals, []string{
		"datetime", "level", "description",
		"app_id", "type", "category", "event",
	})
}

func (s *SlogSuite) TestLogLoggerDisabled(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type sysEvent struct {
		baseAttrs
		Event string `json:"event"`
	}

	logger.LogLoggerDisabled()

	var obtained sysEvent
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Since(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "CRITICAL")
	c.Check(obtained.Description, Equals, "Security logging disabled")
	c.Check(obtained.AppID, Equals, s.appID)
	c.Check(obtained.Type, Equals, "security")
	c.Check(obtained.Category, Equals, "SYS")
	c.Check(obtained.Event, Equals, "sys_logging_disabled")

	// verify key order for human readability
	keys, err := orderedKeys(s.buf.Bytes())
	c.Assert(err, IsNil)
	c.Check(keys, DeepEquals, []string{
		"datetime", "level", "description",
		"app_id", "type", "category", "event",
	})
}

func (s *SlogSuite) TestLogLoginSuccess(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type LoginSuccess struct {
		baseAttrs
		Event string `json:"event"`
		User  struct {
			ID             int64  `json:"snapd-user-id"`
			StoreUserName  string `json:"store-user-name"`
			StoreUserEmail string `json:"store-user-email"`
			Expiration     string `json:"expiration"`
		} `json:"user"`
	}

	user := seclog.SnapdUser{
		ID:             42,
		StoreUserEmail: "user@gmail.com",
		StoreUserName:  "jdoe",
	}
	logger.LogLoginSuccess(user)

	var obtained LoginSuccess
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Since(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "INFO")
	c.Check(obtained.Description, Equals, "User 42:user@gmail.com:jdoe login success")
	c.Check(obtained.AppID, Equals, s.appID)
	c.Check(obtained.Event, Equals, "authn_login_success")
	c.Check(obtained.User.ID, Equals, int64(42))
	c.Check(obtained.User.StoreUserEmail, Equals, "user@gmail.com")
	c.Check(obtained.User.StoreUserName, Equals, "jdoe")
	c.Check(obtained.User.Expiration, Equals, "never")

	// verify key order for human readability
	keys, err := orderedKeys(s.buf.Bytes())
	c.Assert(err, IsNil)
	c.Check(keys, DeepEquals, []string{
		"datetime", "level", "description",
		"app_id", "type", "category", "event", "user",
	})
}

func (s *SlogSuite) TestLogLoginSuccessWithExpiration(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type LoginSuccess struct {
		baseAttrs
		Event string `json:"event"`
		User  struct {
			ID             int64  `json:"snapd-user-id"`
			StoreUserName  string `json:"store-user-name"`
			StoreUserEmail string `json:"store-user-email"`
			Expiration     string `json:"expiration"`
		} `json:"user"`
	}

	expiry := time.Date(2026, 6, 15, 12, 0, 0, 0, time.UTC)
	user := seclog.SnapdUser{
		ID:             42,
		StoreUserEmail: "user@gmail.com",
		StoreUserName:  "jdoe",
		Expiration:     expiry,
	}
	logger.LogLoginSuccess(user)

	var obtained LoginSuccess
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(obtained.User.Expiration, Equals, "2026-06-15T12:00:00Z")
}

func (s *SlogSuite) TestLogLoginFailure(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	type loginFailure struct {
		baseAttrs
		Event string `json:"event"`
		User  struct {
			ID             int64  `json:"snapd-user-id"`
			StoreUserName  string `json:"store-user-name"`
			StoreUserEmail string `json:"store-user-email"`
			Expiration     string `json:"expiration"`
		} `json:"user"`
		Error struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}

	user := seclog.SnapdUser{
		ID:             42,
		StoreUserEmail: "user@gmail.com",
		StoreUserName:  "jdoe",
	}
	logger.LogLoginFailure(user, seclog.Reason{Code: seclog.ReasonInvalidCredentials, Message: "invalid credentials"})

	var obtained loginFailure
	err := json.Unmarshal(s.buf.Bytes(), &obtained)
	c.Assert(err, IsNil)
	c.Check(time.Since(obtained.Datetime) < time.Second, Equals, true)
	c.Check(obtained.Level, Equals, "WARN")
	c.Check(obtained.Description, Equals, "User 42:user@gmail.com:jdoe login failure: invalid-credentials:invalid credentials")
	c.Check(obtained.AppID, Equals, s.appID)
	c.Check(obtained.Event, Equals, "authn_login_failure")
	c.Check(obtained.User.ID, Equals, int64(42))
	c.Check(obtained.User.StoreUserEmail, Equals, "user@gmail.com")
	c.Check(obtained.User.StoreUserName, Equals, "jdoe")
	c.Check(obtained.User.Expiration, Equals, "never")
	c.Check(obtained.Error.Code, Equals, seclog.ReasonInvalidCredentials)
	c.Check(obtained.Error.Message, Equals, "invalid credentials")

	// verify key order for human readability
	keys, err := orderedKeys(s.buf.Bytes())
	c.Assert(err, IsNil)
	c.Check(keys, DeepEquals, []string{
		"datetime", "level", "description",
		"app_id", "type", "category", "event", "user", "error",
	})
}

func (s *SlogSuite) TestLevelFiltering(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appID, seclog.LevelWarn)
	c.Assert(logger, NotNil)

	// LevelInfo is below LevelWarn — should be filtered out
	logger.LogLoggerEnabled()
	c.Check(s.buf.Len(), Equals, 0)

	// LevelWarn meets the threshold — should be emitted
	logger.LogLoginFailure(seclog.SnapdUser{ID: 1}, seclog.Reason{Code: seclog.ReasonInternal, Message: "test"})
	c.Check(s.buf.Len() > 0, Equals, true)
}
