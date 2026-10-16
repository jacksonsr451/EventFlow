import assert from "node:assert/strict";
import test from "node:test";
import {
  createAuthorizationRequest,
  validateAuthorizationCallback,
} from "../src/oidc-pkce.ts";
import {
  createDesktopTokenStore,
  createSecureAuthorizationTransactionStore,
  createVsCodeTokenStore,
  logoutNative,
  refreshNativeTokens,
} from "../src/secure-token-store.ts";

const config = {
  issuer: "https://id.example.test/realms/eventflow",
  authorizationEndpoint: "https://id.example.test/realms/eventflow/protocol/openid-connect/auth",
  clientId: "eventflow-desktop",
  redirectUri: "eventflow://auth/callback",
};

test("authorization request uses PKCE S256, state, and nonce without a client secret", async () => {
  const request = await createAuthorizationRequest(config, 1000);
  const url = new URL(request.url);
  assert.equal(url.searchParams.get("response_type"), "code");
  assert.equal(url.searchParams.get("code_challenge_method"), "S256");
  assert.match(url.searchParams.get("code_challenge"), /^[A-Za-z0-9_-]{43}$/);
  assert.equal(url.searchParams.get("state"), request.transaction.state);
  assert.equal(url.searchParams.get("nonce"), request.transaction.nonce);
  assert.equal(url.searchParams.has("client_secret"), false);
  assert.equal(url.searchParams.has("code_verifier"), false);
});

test("callback validation binds state, redirect URI, and transaction age", async () => {
  const request = await createAuthorizationRequest(config, 1000);
  const callback = new URL(config.redirectUri);
  callback.searchParams.set("code", "one-use-code");
  callback.searchParams.set("state", request.transaction.state);
  const result = validateAuthorizationCallback(
    callback.toString(),
    config.redirectUri,
    request.transaction,
    2000,
  );
  assert.equal(result.code, "one-use-code");
  assert.equal(result.codeVerifier, request.transaction.codeVerifier);
  assert.equal(result.nonce, request.transaction.nonce);

  callback.searchParams.set("state", "attacker-state");
  assert.throws(() =>
    validateAuthorizationCallback(callback.toString(), config.redirectUri, request.transaction, 2000),
  );
  assert.throws(() =>
    validateAuthorizationCallback(callback.toString(), "eventflow://attacker/callback", request.transaction, 2000),
  );
  assert.throws(() => {
    const wrongCustomScheme = new URL("attacker://other/callback");
    wrongCustomScheme.searchParams.set("code", "one-use-code");
    wrongCustomScheme.searchParams.set("state", request.transaction.state);
    validateAuthorizationCallback(
      wrongCustomScheme.toString(),
      config.redirectUri,
      request.transaction,
      2000,
    );
  });
  assert.throws(() =>
    validateAuthorizationCallback(callback.toString(), config.redirectUri, request.transaction, 700_000),
  );
});

test("VS Code and desktop adapters use only the injected protected store", async () => {
  const values = new Map();
  const calls = [];
  const store = {
    async get(key) {
      calls.push(["get", key]);
      return values.get(key);
    },
    async store(key, value) {
      calls.push(["store", key]);
      values.set(key, value);
    },
    async delete(key) {
      calls.push(["delete", key]);
      values.delete(key);
    },
  };
  for (const adapter of [createVsCodeTokenStore(store), createDesktopTokenStore(store)]) {
    await adapter.save({ accessToken: "access", refreshToken: "refresh", expiresAt: 123 });
    assert.deepEqual(await adapter.load(), {
      accessToken: "access",
      refreshToken: "refresh",
      expiresAt: 123,
    });
    await adapter.clear();
    assert.equal(await adapter.load(), undefined);
  }
  assert.ok(calls.every(([, key]) => key === "eventflow.oidc.tokens.v1"));
});

test("native PKCE transaction is single-use in the protected store", async () => {
  const values = new Map();
  const store = {
    async get(key) { return values.get(key); },
    async store(key, value) { values.set(key, value); },
    async delete(key) { values.delete(key); },
  };
  const pending = createSecureAuthorizationTransactionStore(store);
  const transaction = { state: "state", nonce: "nonce", codeVerifier: "verifier", createdAt: 1 };
  await pending.save(transaction);
  const concurrent = await Promise.all([pending.consume(), pending.consume()]);
  assert.equal(concurrent.filter(Boolean).length, 1);
  assert.deepEqual(concurrent.find(Boolean), transaction);
  assert.equal(await pending.consume(), undefined);
});

test("native refresh uses a public-client request and requires rotation", async () => {
  let submitted;
  const tokens = await refreshNativeTokens(
    "https://id.example.test/realms/eventflow",
    "https://id.example.test/realms/eventflow/token",
    "eventflow-desktop",
    "refresh-secret",
    async (_url, init) => {
      submitted = new URLSearchParams(init.body);
      return new Response(JSON.stringify({
        access_token: "new-access",
        refresh_token: "new-refresh",
        token_type: "Bearer",
        expires_in: 300,
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    },
  );
  assert.equal(submitted.get("client_id"), "eventflow-desktop");
  assert.equal(submitted.has("client_secret"), false);
  assert.equal(tokens.refreshToken, "new-refresh");
  await assert.rejects(
    refreshNativeTokens(
      "https://id.example.test/realms/eventflow",
      "https://attacker.example/token",
      "eventflow-desktop",
      "refresh-secret",
      async () => {
        throw new Error("off-origin endpoint must not be requested");
      },
    ),
    /share the configured issuer origin/,
  );
  await assert.rejects(
    refreshNativeTokens(
      "https://id.example.test/realms/eventflow",
      "https://id.example.test/realms/eventflow/token",
      "eventflow-desktop",
      "refresh-secret",
      async () => new Response(JSON.stringify({
        access_token: "new-access",
        refresh_token: "refresh-secret",
        token_type: "Bearer",
        expires_in: 300,
      }), { status: 200 }),
    ),
    /rotation was not performed/,
  );
});

test("concurrent refreshes on one client adapter are single-flight", async () => {
  const values = new Map([["eventflow.oidc.tokens.v1", JSON.stringify({
    accessToken: "old-access",
    refreshToken: "old-refresh",
    expiresAt: 1,
  })]]);
  const store = {
    async get(key) { return values.get(key); },
    async store(key, value) { values.set(key, value); },
    async delete(key) { values.delete(key); },
  };
  const adapter = createDesktopTokenStore(store);
  let requests = 0;
  const fetcher = async () => {
    requests += 1;
    await new Promise((resolve) => setTimeout(resolve, 5));
    return new Response(JSON.stringify({
      access_token: "new",
      refresh_token: "rotated",
      token_type: "Bearer",
      expires_in: 300,
    }), { status: 200 });
  };
  const [left, right] = await Promise.all([
    adapter.refresh(
      "https://id.example.test/realms/eventflow",
      "https://id.example.test/realms/eventflow/token",
      "eventflow-desktop",
      fetcher,
    ),
    adapter.refresh(
      "https://id.example.test/realms/eventflow",
      "https://id.example.test/realms/eventflow/token",
      "eventflow-desktop",
      fetcher,
    ),
  ]);
  assert.equal(requests, 1);
  assert.deepEqual(left, right);
});

test("native refresh rejection clears protected credentials", async () => {
  const values = new Map([[
    "eventflow.oidc.tokens.v1",
    JSON.stringify({ accessToken: "old", refreshToken: "revoked", expiresAt: 1 }),
  ]]);
  const store = {
    async get(key) { return values.get(key); },
    async store(key, value) { values.set(key, value); },
    async delete(key) { values.delete(key); },
  };
  const adapter = createDesktopTokenStore(store);
  await assert.rejects(
    adapter.refresh(
      "https://id.example.test/realms/eventflow",
      "https://id.example.test/realms/eventflow/token",
      "eventflow-desktop",
      async () => new Response("{}", { status: 401 }),
    ),
  );
  assert.equal(await adapter.load(), undefined);
});

test("native logout clears protected local credentials even when provider revoke fails", async () => {
  const values = new Map([["eventflow.oidc.tokens.v1", JSON.stringify({
    accessToken: "old-access",
    refreshToken: "old-refresh",
    expiresAt: 1,
  })]]);
  const store = {
    async get(key) { return values.get(key); },
    async store(key, value) { values.set(key, value); },
    async delete(key) { values.delete(key); },
  };
  const adapter = createVsCodeTokenStore(store);
  await assert.rejects(
    logoutNative(
      "https://id.example.test/realms/eventflow",
      "https://id.example.test/realms/eventflow/revoke",
      "eventflow-vscode",
      adapter,
      async () => new Response("", { status: 503 }),
    ),
  );
  assert.equal(await adapter.load(), undefined);
});
