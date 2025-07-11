// -*- Mode: Go; indent-tabs-mode: t -*-

/*
 * Copyright (C) 2016 Canonical Ltd
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

package signtool_test

import (
	"encoding/json"
	"strconv"
	"testing"
	"time"

	. "gopkg.in/check.v1"

	"github.com/snapcore/snapd/asserts"
	"github.com/snapcore/snapd/asserts/assertstest"
	"github.com/snapcore/snapd/asserts/signtool"
)

func TestSigntool(t *testing.T) { TestingT(t) }

type signSuite struct {
	keypairMgr asserts.KeypairManager
	testKeyID  string
	testAccKey *asserts.AccountKey
}

var _ = Suite(&signSuite{})

func (s *signSuite) SetUpSuite(c *C) {
	testKey, _ := assertstest.GenerateKey(752)

	s.keypairMgr = asserts.NewMemoryKeypairManager()
	s.keypairMgr.Put(testKey)
	s.testKeyID = testKey.PublicKey().ID()

	encPubKey, err := asserts.EncodePublicKey(testKey.PublicKey())
	c.Assert(err, IsNil)
	s.testAccKey = assertstest.FakeAssertionWithBody(encPubKey,
		map[string]any{
			"type":                "account-key",
			"authority-id":        "canonical",
			"public-key-sha3-384": s.testKeyID,
			"account-id":          "user-id1",
			"since":               "2015-11-01T20:00:00Z",
			"body-length":         strconv.Itoa(len(encPubKey)),
			"constraints": []any{
				map[string]any{
					"headers": map[string]any{
						"type":  "model",
						"model": `baz-.*`,
					},
				},
			},
		},
	).(*asserts.AccountKey)
}

func expectedModelHeaders(a asserts.Assertion) map[string]any {
	m := map[string]any{
		"type":           "model",
		"authority-id":   "user-id1",
		"series":         "16",
		"brand-id":       "user-id1",
		"model":          "baz-3000",
		"architecture":   "amd64",
		"gadget":         "brand-gadget",
		"kernel":         "baz-linux",
		"store":          "brand-store",
		"required-snaps": []any{"foo", "bar"},
		"timestamp":      "2015-11-25T20:00:00Z",
	}
	if a != nil {
		m["sign-key-sha3-384"] = a.SignKeyID()
	}
	return m
}

func exampleJSON(overrides map[string]any) []byte {
	m := expectedModelHeaders(nil)
	for k, v := range overrides {
		if v == nil {
			delete(m, k)
		} else {
			m[k] = v
		}
	}
	b, err := json.Marshal(m)
	if err != nil {
		panic(err)
	}
	return b
}

func (s *signSuite) TestSignJSON(c *C) {
	opts := signtool.Options{
		KeyID: s.testKeyID,

		Statement: exampleJSON(nil),
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 0)
	expectedHeaders := expectedModelHeaders(a)
	c.Check(a.Headers(), DeepEquals, expectedHeaders)

	for n, v := range a.Headers() {
		c.Check(v, DeepEquals, expectedHeaders[n], Commentf(n))
	}

	c.Check(a.Body(), IsNil)
}

func (s *signSuite) TestSignJSONWithAccountKeyCrossCheck(c *C) {
	opts := signtool.Options{
		KeyID:      s.testKeyID,
		AccountKey: s.testAccKey,

		Statement: exampleJSON(nil),
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 0)
	expectedHeaders := expectedModelHeaders(a)
	c.Check(a.Headers(), DeepEquals, expectedHeaders)

	for n, v := range a.Headers() {
		c.Check(v, DeepEquals, expectedHeaders[n], Commentf(n))
	}

	c.Check(a.Body(), IsNil)
}

func (s *signSuite) TestSignJSONWithBodyAndRevision(c *C) {
	statement := exampleJSON(map[string]any{
		"body":     "BODY",
		"revision": "11",
	})
	opts := signtool.Options{
		KeyID: s.testKeyID,

		Statement: statement,
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 11)

	expectedHeaders := expectedModelHeaders(a)
	expectedHeaders["revision"] = "11"
	expectedHeaders["body-length"] = "4"

	c.Check(a.Headers(), DeepEquals, expectedHeaders)

	c.Check(a.Body(), DeepEquals, []byte("BODY"))
}

func (s *signSuite) TestSignJSONWithBodyAndComplementRevision(c *C) {
	statement := exampleJSON(map[string]any{
		"body": "BODY",
	})
	opts := signtool.Options{
		KeyID: s.testKeyID,

		Statement: statement,
		Complement: map[string]any{
			"revision": "11",
		},
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 11)

	expectedHeaders := expectedModelHeaders(a)
	expectedHeaders["revision"] = "11"
	expectedHeaders["body-length"] = "4"

	c.Check(a.Headers(), DeepEquals, expectedHeaders)

	c.Check(a.Body(), DeepEquals, []byte("BODY"))
}

func (s *signSuite) TestSignJSONWithRevisionAndComplementBodyAndRepeatedType(c *C) {
	statement := exampleJSON(map[string]any{
		"revision": "11",
	})
	opts := signtool.Options{
		KeyID: s.testKeyID,

		Statement: statement,
		Complement: map[string]any{
			"type": "model",
			"body": "BODY",
		},
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 11)

	expectedHeaders := expectedModelHeaders(a)
	expectedHeaders["revision"] = "11"
	expectedHeaders["body-length"] = "4"

	c.Check(a.Headers(), DeepEquals, expectedHeaders)

	c.Check(a.Body(), DeepEquals, []byte("BODY"))
}

func (s *signSuite) TestSignErrors(c *C) {
	opts := signtool.Options{
		KeyID: s.testKeyID,
	}

	emptyList := []any{}

	tests := []struct {
		expError        string
		brokenStatement []byte
		complement      map[string]any
		accKey          *asserts.AccountKey
	}{
		{`cannot parse the assertion input as JSON:.*`,
			[]byte("\x00"),
			nil, nil,
		},
		{`invalid assertion type: what`,
			exampleJSON(map[string]any{"type": "what"}),
			nil, nil,
		},
		{`assertion type must be a string, not: \[\]`,
			exampleJSON(map[string]any{"type": emptyList}),
			nil, nil,
		},
		{`missing assertion type header`,
			exampleJSON(map[string]any{"type": nil}),
			nil, nil,
		},
		{"revision should be positive: -10",
			exampleJSON(map[string]any{"revision": "-10"}),
			nil, nil,
		},
		{`"authority-id" header is mandatory`,
			exampleJSON(map[string]any{"authority-id": nil}),
			nil, nil,
		},
		{`body if specified must be a string`,
			exampleJSON(map[string]any{"body": emptyList}),
			nil, nil,
		},
		{`repeated assertion type does not match`,
			exampleJSON(nil),
			map[string]any{"type": "foo"}, nil,
		},
		{`complementary header "kernel" clashes with assertion input`,
			exampleJSON(nil),
			map[string]any{"kernel": "foo"}, nil,
		},
		{`authority-id does not match the account-id of the signing account-key`,
			exampleJSON(map[string]any{"authority-id": "user-id2", "brand-id": "user-id2"}),
			nil, s.testAccKey,
		},
		{`the assertion headers do not match the constraints of the signing account-key`,
			exampleJSON(map[string]any{"model": "bar"}),
			nil, s.testAccKey,
		},
	}

	for _, t := range tests {
		fresh := opts

		fresh.Statement = t.brokenStatement
		fresh.Complement = t.complement
		fresh.AccountKey = t.accKey

		_, err := signtool.Sign(&fresh, s.keypairMgr)
		c.Check(err, ErrorMatches, t.expError)
	}
}

func (s *signSuite) TestSignFormatsAssertionsWithJSONBody(c *C) {
	statement, err := json.Marshal(map[string]any{
		"type":         "confdb-schema",
		"account-id":   "user-id1",
		"authority-id": "user-id1",
		"revision":     "1",
		"timestamp":    "2025-05-09T16:00:00Z",
		"name":         "foo",
		"views": map[string]any{
			"foo": map[string]any{
				"rules": []any{
					map[string]any{"storage": "a"},
				},
			},
		},
		// use unindented, unsorted JSON to check formatting
		"body": `{"storage": {
  "schema": {
    "b": "int",
      "a": "string",
		"c": { "type": "number", "max": 1.0 }
  }
}}`,
	})
	c.Assert(err, IsNil)

	opts := signtool.Options{
		KeyID:     s.testKeyID,
		Statement: statement,
	}

	expected := `{
  "storage": {
    "schema": {
      "a": "string",
      "b": "int",
      "c": {
        "max": 1,
        "type": "number"
      }
    }
  }
}`

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ConfdbSchemaType)
	c.Check(string(a.Body()), DeepEquals, expected)
}

func (s *signSuite) TestSignJSONWithUpdateTimestamp(c *C) {
	opts := signtool.Options{
		KeyID: s.testKeyID,

		Statement:       exampleJSON(nil),
		UpdateTimestamp: true,
	}

	assertText, err := signtool.Sign(&opts, s.keypairMgr)
	c.Assert(err, IsNil)

	a, err := asserts.Decode(assertText)
	c.Assert(err, IsNil)

	c.Check(a.Type(), Equals, asserts.ModelType)
	c.Check(a.Revision(), Equals, 0)

	// Retrieve the header "timestamp" from the assertion.
	header := a.Headers()
	tsValue, ok := header["timestamp"].(string)
	c.Assert(ok, Equals, true)

	// The original expected timestamp from expectedModelHeaders is "2015-11-25T20:00:00Z".
	// Verify that the timestamp was indeed updated.
	c.Check(tsValue, Not(Equals), "2015-11-25T20:00:00Z")

	// Parse the updated timestamp and verify it is a valid RFC3339 timestamp near the current time.
	updatedTime, err := time.Parse(time.RFC3339, tsValue)
	c.Assert(err, IsNil)
	now := time.Now()
	diff := now.Sub(updatedTime)
	if diff < 0 {
		diff = -diff
	}
	// Allow a difference of up to 5 minutes.
	c.Check(diff < 5*time.Minute, Equals, true)

	// For a deep equality check, build the expected headers and replace the "timestamp" field
	expectedHeaders := expectedModelHeaders(a)
	expectedHeaders["timestamp"] = tsValue
	c.Check(header, DeepEquals, expectedHeaders)

	c.Check(a.Body(), IsNil)
}
