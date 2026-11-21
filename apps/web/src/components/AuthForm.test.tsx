import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { AuthFormView, OAUTH_ERRORS } from "./AuthForm";

const base = { next: "/viewer", errors: [] as string[] };

test("login form has labelled email and password fields", () => {
  const html = renderToStaticMarkup(<AuthFormView mode="login" providers={{ github: false, google: false }} {...base} />);
  expect(html).toMatch(/<label>\s*Email\s*<input[^>]*type="email"/);
  expect(html).toMatch(/<label>\s*Password\s*<input[^>]*type="password"/);
  expect(html).toContain('href="/register?next=%2Fviewer"');
});

test("only configured providers get a button", () => {
  const html = renderToStaticMarkup(<AuthFormView mode="login" providers={{ github: true, google: false }} {...base} />);
  expect(html).toContain("Continue with GitHub");
  expect(html).toContain('href="/api/v1/auth/oauth/github/login?next=%2Fviewer"');
  expect(html).not.toContain("Google");
  const none = renderToStaticMarkup(<AuthFormView mode="login" providers={{ github: false, google: false }} {...base} />);
  expect(none).not.toContain("Continue with");
});

test("register form adds a name field and a minimum password length; errors are announced", () => {
  const html = renderToStaticMarkup(
    <AuthFormView mode="register" providers={{ github: false, google: true }} next="/" errors={["bad"]} />,
  );
  expect(html).toContain("Display name");
  expect(html).toContain('minLength="10"');
  expect(html).toContain('role="alert"');
  expect(html).toContain("Continue with Google");
});

test("oauth callback error codes map to readable messages", () => {
  expect(OAUTH_ERRORS.email_exists).toBe("An account with this email exists. Sign in with your password.");
});
