import { expect, test } from "vitest";
import { credentialErrors, getProviders, login, loginUrl, me, oauthUrl, register, safeNext, updateProfile } from "./auth";

const reply = (status: number, body: unknown) =>
  (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

test("unauthenticated visitors are redirected to /login with a safe next", () => {
  expect(loginUrl("/viewer", "?project=abc")).toBe("/login?next=%2Fviewer%3Fproject%3Dabc");
  expect(loginUrl("/")).toBe("/login");
});

test("safeNext only allows same-site relative paths", () => {
  expect(safeNext("/viewer?x=1")).toBe("/viewer?x=1");
  for (const bad of ["//evil.example", "https://evil.example", "/\\evil", "", null, undefined, "viewer"]) {
    expect(safeNext(bad)).toBe("/");
  }
});

test("oauth button links carry next and hit the same-origin API", () => {
  expect(oauthUrl("github", "/viewer")).toBe("/api/v1/auth/oauth/github/login?next=%2Fviewer");
  expect(oauthUrl("google", "//evil")).toBe("/api/v1/auth/oauth/google/login?next=%2F");
});

test("credential checks", () => {
  expect(credentialErrors("nope", "x", "login")).toEqual(["Enter a valid email address."]);
  expect(credentialErrors("a@b.co", "", "login")).toEqual(["Enter your password."]);
  expect(credentialErrors("a@b.co", "short", "register")).toEqual(["Password must be at least 10 characters."]);
  expect(credentialErrors("a@b.co", "long enough pw", "register")).toEqual([]);
});

test("login posts credentials with cookies and returns the user", async () => {
  let seen: { url: string; init: RequestInit } | undefined;
  const f = (async (url: string, init: RequestInit) => {
    seen = { url, init };
    return new Response(JSON.stringify({ id: "1", email: "a@b.co", display_name: "a", has_password: true }));
  }) as unknown as typeof fetch;
  const r = await login("a@b.co", "pw", f);
  expect(r.ok && r.email).toBe("a@b.co");
  expect(seen!.url).toBe("/api/v1/auth/login");
  expect(seen!.init.credentials).toBe("include");
  expect(JSON.parse(seen!.init.body as string)).toEqual({ email: "a@b.co", password: "pw" });
});

test("bad login surfaces the server's generic message", async () => {
  expect(await login("a@b.co", "x", reply(401, { detail: "invalid email or password" }))).toMatchObject({
    ok: false,
    kind: "unauthorized",
    message: "invalid email or password",
  });
});

test("me is unauthorized without a session; register/profile errors pass through", async () => {
  expect(await me(reply(401, { detail: "not authenticated" }))).toMatchObject({ kind: "unauthorized" });
  expect(await register("a@b.co", "longenoughpw", "", reply(409, { detail: "exists" }))).toMatchObject({ message: "exists" });
  expect(await updateProfile({ new_password: "x" }, reply(400, { detail: "current password is incorrect" }))).toMatchObject({
    message: "current password is incorrect",
  });
});

test("providers default to hidden when the API is unreachable", async () => {
  const down = (async () => {
    throw new TypeError("fail");
  }) as unknown as typeof fetch;
  expect(await getProviders(down)).toEqual({ github: false, google: false });
  expect(await getProviders(reply(200, { github: true, google: false }))).toEqual({ github: true, google: false });
});
