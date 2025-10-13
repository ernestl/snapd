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

	. "gopkg.in/check.v1"

	"github.com/snapcore/snapd/seclog"
	"github.com/snapcore/snapd/testutil"
)

type SecLogSuite struct {
	testutil.BaseTest
	buf   *bytes.Buffer
	appId string
}

var _ = Suite(&SecLogSuite{})

func (s *SecLogSuite) SetUpSuite(c *C) {
	s.buf = &bytes.Buffer{}
	s.appId = "canonical.snapd"
}

func (s *SecLogSuite) SetUpTest(c *C) {
	s.BaseTest.SetUpTest(c)
	s.buf.Reset()
}

func (s *SecLogSuite) TearDownTest(c *C) {
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

/*func (s *SecLogSuite) TestLogLoginSuccess(c *C) {
}

func (s *SecLogSuite) TestLogLoginFailure(c *C) {
}*/
