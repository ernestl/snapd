// -*- Mode: Go; indent-tabs-mode: t -*-
//go:build !go1.21 || noslog

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
	"errors"
	"testing"

	. "gopkg.in/check.v1"

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

// extractSloglogger is a test helper to extract [seclog.NoopLogger] from Logger.
func extractNoopLogger(logger seclog.Logger) (*seclog.NoopLogger, error) {
	if l, ok := logger.(*seclog.NoopLogger); !ok {
		return nil, errors.New("cannot extract noop logger")
	} else {
		return l, nil
	}
}

func (s *SecLogSlogSuite) TestNew(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	_, err := extractNoopLogger(logger)
	c.Assert(err, IsNil)
}

func (s *SecLogSlogSuite) TestLogLoginSuccess(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	logger.LogLoginSuccess("user@gmail.com")
	c.Assert(s.buf.Len(), Equals, 0)
}

func (s *SecLogSlogSuite) TestLogLoginFailure(c *C) {
	logger := seclog.NewSlogLogger(s.buf, s.appId, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	logger.LogLoginFailure("user@gmail.com")
	c.Assert(s.buf.Len(), Equals, 0)
}
