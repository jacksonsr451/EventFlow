/** Platform-neutral OIDC Authorization Code + PKCE helpers. */

export interface OidcClientConfiguration {
  issuer: string;
  authorizationEndpoint: string;
  clientId: string;
  redirectUri: string;
  scopes?: readonly string[];
}

export interface AuthorizationTransaction {
  state: string;
  nonce: string;
  codeVerifier: string;
  createdAt: number;
}

export interface AuthorizationRequest {
  url: string;
  transaction: AuthorizationTransaction;
}

export interface AuthorizationCallbackResult {
  code: string;
  codeVerifier: string;
  nonce: string;
}

function randomUrlToken(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function assertTrustedEndpoint(issuer: string, endpoint: string): void {
  const issuerUrl = new URL(issuer);
  const endpointUrl = new URL(endpoint);
  const isLoopback = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(
    issuerUrl.hostname,
  );
  if (issuerUrl.protocol !== "https:" && !isLoopback) {
    throw new Error("OIDC issuer must use HTTPS outside loopback development");
  }
  if (
    issuerUrl.username ||
    issuerUrl.password ||
    issuerUrl.search ||
    issuerUrl.hash ||
    endpointUrl.username ||
    endpointUrl.password ||
    endpointUrl.search ||
    endpointUrl.hash
  ) {
    throw new Error("OIDC issuer and authorization endpoint must not contain credentials or fragments");
  }
  if (issuerUrl.origin !== endpointUrl.origin) {
    throw new Error("OIDC authorization endpoint must share the configured issuer origin");
  }
}

export async function createAuthorizationRequest(
  config: OidcClientConfiguration,
  now = Date.now(),
): Promise<AuthorizationRequest> {
  assertTrustedEndpoint(config.issuer, config.authorizationEndpoint);
  const transaction: AuthorizationTransaction = {
    state: randomUrlToken(),
    nonce: randomUrlToken(),
    codeVerifier: randomUrlToken(48),
    createdAt: now,
  };
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(transaction.codeVerifier),
  );
  const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
  const url = new URL(config.authorizationEndpoint);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("scope", (config.scopes ?? ["openid", "eventflow-api-audience"]).join(" "));
  url.searchParams.set("state", transaction.state);
  url.searchParams.set("nonce", transaction.nonce);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return { url: url.toString(), transaction };
}

function constantTimeEqual(left: string, right: string): boolean {
  const a = new TextEncoder().encode(left);
  const b = new TextEncoder().encode(right);
  let mismatch = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    mismatch |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return mismatch === 0;
}

export function validateAuthorizationCallback(
  callbackUrl: string,
  registeredRedirectUri: string,
  transaction: AuthorizationTransaction,
  now = Date.now(),
  maxAgeMs = 10 * 60 * 1000,
): AuthorizationCallbackResult {
  const callback = new URL(callbackUrl);
  const redirect = new URL(registeredRedirectUri);
  if (
    callback.protocol !== redirect.protocol ||
    callback.username !== redirect.username ||
    callback.password !== redirect.password ||
    callback.hostname !== redirect.hostname ||
    callback.port !== redirect.port ||
    callback.pathname !== redirect.pathname ||
    redirect.hash ||
    callback.hash
  ) {
    throw new Error("OIDC callback does not match the registered redirect URI");
  }
  if (now < transaction.createdAt || now - transaction.createdAt > maxAgeMs) {
    throw new Error("OIDC authorization transaction expired");
  }
  if (!constantTimeEqual(callback.searchParams.get("state") ?? "", transaction.state)) {
    throw new Error("OIDC state validation failed");
  }
  if (callback.searchParams.has("error")) {
    // Do not surface provider error_description; it may contain sensitive details.
    throw new Error("OIDC authorization was rejected");
  }
  const code = callback.searchParams.get("code");
  if (!code) throw new Error("OIDC callback did not contain an authorization code");
  return {
    code,
    codeVerifier: transaction.codeVerifier,
    nonce: transaction.nonce,
  };
}
