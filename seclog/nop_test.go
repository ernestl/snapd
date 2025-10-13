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

package seclog_test

import (
	"bytes"
	"testing"

	. "gopkg.in/check.v1"

	"github.com/snapcore/snapd/seclog"
	"github.com/snapcore/snapd/testutil"
)

type NopSuite struct {
	testutil.BaseTest
	buf      *bytes.Buffer
	appID    string
	provider seclog.Provider
}

var _ = Suite(&NopSuite{})

func TestNop(t *testing.T) { TestingT(t) }

func (s *NopSuite) SetUpSuite(c *C) {
	s.buf = &bytes.Buffer{}
	s.appID = "canonical.snapd"
	s.provider = seclog.NopProvider{}
}

func (s *NopSuite) SetUpTest(c *C) {
	s.BaseTest.SetUpTest(c)
}

func (s *NopSuite) TearDownTest(c *C) {
	s.BaseTest.TearDownTest(c)
}

func (s *NopSuite) TestNopProvider(c *C) {
	logger := s.provider.New(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	impl := s.provider.Impl()
	c.Assert(impl, Equals, seclog.ImplNop)
}

func (s *NopSuite) TestLogLoginSuccess(c *C) {
	logger := s.provider.New(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	logger.LogLoginSuccess("user@gmail.com")
	c.Assert(s.buf.Len(), Equals, 0)
}

func (s *NopSuite) TestLogLoginFailure(c *C) {
	logger := s.provider.New(s.buf, s.appID, seclog.LevelInfo)
	c.Assert(logger, NotNil)

	logger.LogLoginFailure("user@gmail.com")
	c.Assert(s.buf.Len(), Equals, 0)
}
