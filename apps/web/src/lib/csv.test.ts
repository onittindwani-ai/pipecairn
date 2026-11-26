import assert from "node:assert/strict";
import { test } from "node:test";
import { parseCsv, summariseCsv } from "./csv.ts";

test("counts data rows and keeps the header out of the count", () => {
  const s = summariseCsv("email,first_name\na@x.test,Ann\nb@x.test,Bo\n");
  assert.equal(s.rows, 2);
  assert.deepEqual(s.columns, ["email", "first_name"]);
  assert.equal(s.hasEmail, true);
});

test("handles quoted commas, doubled quotes, line breaks inside quotes and Windows line ends", () => {
  const rows = parseCsv('email,company\r\na@x.test,"Smith, ""Sons"" & Co"\r\nb@x.test,"two\nlines"\r\n');
  assert.equal(rows[1]![1], 'Smith, "Sons" & Co');
  assert.equal(rows[2]![1], "two\nlines");
  assert.equal(rows.length, 3);
});

test("ignores a byte order mark and blank lines", () => {
  const s = summariseCsv("﻿email\n\na@x.test\n\n");
  assert.deepEqual(s.columns, ["email"]);
  assert.equal(s.rows, 1);
});

test("limits the preview and reports a missing email column", () => {
  const body = Array.from({ length: 9 }, (_, i) => `n${i}`).join("\n");
  const s = summariseCsv(`name\n${body}\n`);
  assert.equal(s.rows, 9);
  assert.equal(s.preview.length, 5);
  assert.equal(s.hasEmail, false);
});

test("an empty file has no rows", () => {
  assert.deepEqual(summariseCsv(""), { columns: [], rows: 0, preview: [], hasEmail: false });
});

test("an email column is recognised the way the server recognises it", () => {
  for (const name of ["Email", " E-mail ", "email address", "Email_Address", "MAIL"]) assert.equal(summariseCsv(`${name},first_name\na@x.test,Ann\n`).hasEmail, true, name);
  assert.equal(summariseCsv("name,phone\nAnn,1\n").hasEmail, false);
});
