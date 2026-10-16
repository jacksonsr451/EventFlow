/** Minimal adapter contracts; concrete apps must supply OS/VS Code secure storage. */

export interface SecretStorage {
  get(key: string): Promise<string | undefined>;
  store(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
}

export interface TokenSet {
  accessToken: string;
  refreshToken?: string;
  expiresAt: number;
}

const TOKEN_KEY = "eventflow.oidc.tokens.v1";
const TRANSACTION_KEY = "eventflow.oidc.transaction.v1";

export interface PendingAuthorizationTransaction {
  state: string;
  nonce: string;
  codeVerifier: string;
  createdAt: number;
}

export class SecureTokenStore {
  #refreshInFlight: Promise<TokenSet> | undefined;
  #storage: SecretStorage;

  constructor(storage: SecretStorage) {
    this.#storage = storage;
  }

  async save(tokens: TokenSet): Promise<void> {
    if (!tokens.accessToken || !Number.isFinite(tokens.expiresAt)) {
      throw new Error("Invalid token set");
    }
    await this.#storage.store(TOKEN_KEY, JSON.stringify(tokens));
  }

  async load(): Promise<TokenSet | undefined> {
    const serialized = await this.#storage.get(TOKEN_KEY);
    if (serialized === undefined) return undefined;
    let value: unknown;
    try {
      value = JSON.parse(serialized);
    } catch {
      await this.clear();
      return undefined;
    }
    if (
      typeof value !== "object" ||
      value === null ||
      typeof (value as TokenSet).accessToken !== "string" ||
      !(value as TokenSet).accessToken ||
      !Number.isFinite((value as TokenSet).expiresAt) ||
      ((value as TokenSet).refreshToken !== undefined &&
        typeof (value as TokenSet).refreshToken !== "string")
    ) {
      await this.clear();
      return undefined;
    }
    return value as TokenSet;
  }

  async clear(): Promise<void> {
    await this.#storage.delete(TOKEN_KEY);
  }

  async refresh(
    issuer: string,
    tokenEndpoint: string,
    clientId: string,
    fetcher: typeof fetch = fetch,
  ): Promise<TokenSet> {
    if (this.#refreshInFlight) return this.#refreshInFlight;
    this.#refreshInFlight = (async () => {
      const existing = await this.load();
      if (!existing?.refreshToken) throw new Error("No refresh credential is available");
      const replacement = await refreshNativeTokens(
        issuer,
        tokenEndpoint,
        clientId,
        existing.refreshToken,
        fetcher,
      );
      await this.save(replacement);
      return replacement;
    })();
    try {
      return await this.#refreshInFlight;
    } catch (error) {
      try {
        await this.clear();
      } catch {
        // Preserve the provider/storage failure; callers must still reauthenticate.
      }
      throw error;
    } finally {
      this.#refreshInFlight = undefined;
    }
  }
}

/** VS Code SecretStorage is structurally compatible with this adapter. */
export function createVsCodeTokenStore(secretStorage: SecretStorage): SecureTokenStore {
  return new SecureTokenStore(secretStorage);
}

/** A Tauri keychain plugin adapter can implement this interface without exposing tokens to WebView state. */
export function createDesktopTokenStore(keychain: SecretStorage): SecureTokenStore {
  return new SecureTokenStore(keychain);
}

export class SecureAuthorizationTransactionStore {
  #storage: SecretStorage;
  #consumeInProgress = false;

  constructor(storage: SecretStorage) {
    this.#storage = storage;
  }

  async save(transaction: PendingAuthorizationTransaction): Promise<void> {
    await this.#storage.store(TRANSACTION_KEY, JSON.stringify(transaction));
  }

  async consume(): Promise<PendingAuthorizationTransaction | undefined> {
    if (this.#consumeInProgress) return undefined;
    this.#consumeInProgress = true;
    try {
      const serialized = await this.#storage.get(TRANSACTION_KEY);
      await this.#storage.delete(TRANSACTION_KEY);
      if (serialized === undefined) return undefined;
      let value: unknown;
      try {
        value = JSON.parse(serialized);
      } catch {
        return undefined;
      }
      if (
        typeof value !== "object" ||
        value === null ||
        typeof (value as PendingAuthorizationTransaction).state !== "string" ||
        typeof (value as PendingAuthorizationTransaction).nonce !== "string" ||
        typeof (value as PendingAuthorizationTransaction).codeVerifier !== "string" ||
        typeof (value as PendingAuthorizationTransaction).createdAt !== "number"
      ) {
        return undefined;
      }
      return value as PendingAuthorizationTransaction;
    } finally {
      this.#consumeInProgress = false;
    }
  }
}

/** Store pending native-client PKCE state only in the supplied protected store. */
export function createSecureAuthorizationTransactionStore(
  secretStorage: SecretStorage,
): SecureAuthorizationTransactionStore {
  return new SecureAuthorizationTransactionStore(secretStorage);
}

export async function refreshNativeTokens(
  issuer: string,
  tokenEndpoint: string,
  clientId: string,
  refreshToken: string,
  fetcher: typeof fetch = fetch,
): Promise<TokenSet> {
  const endpoint = assertTrustedEndpoint(issuer, tokenEndpoint, "token");
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: clientId,
    refresh_token: refreshToken,
  });
  const response = await fetcher(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body,
    cache: "no-store",
    redirect: "error",
  });
  if (!response.ok) throw new Error("OIDC refresh was rejected");
  const result: unknown = await response.json();
  if (
    typeof result !== "object" ||
    result === null ||
    typeof (result as Record<string, unknown>).access_token !== "string" ||
    !(result as Record<string, unknown>).access_token ||
    typeof (result as Record<string, unknown>).refresh_token !== "string" ||
    !(result as Record<string, unknown>).refresh_token ||
    (result as Record<string, unknown>).token_type !== "Bearer" ||
    typeof (result as Record<string, unknown>).expires_in !== "number" ||
    !Number.isFinite((result as Record<string, unknown>).expires_in) ||
    ((result as Record<string, unknown>).expires_in as number) <= 0
  ) {
    throw new Error("OIDC refresh response is invalid");
  }
  const values = result as Record<string, unknown>;
  if (values.refresh_token === refreshToken) {
    throw new Error("OIDC refresh token rotation was not performed");
  }
  return {
    accessToken: values.access_token as string,
    refreshToken: values.refresh_token as string,
    expiresAt: Date.now() + (values.expires_in as number) * 1000,
  };
}

export async function logoutNative(
  issuer: string,
  revocationEndpoint: string,
  clientId: string,
  store: SecureTokenStore,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const existing = await store.load();
  try {
    if (existing?.refreshToken) {
      const endpoint = assertTrustedEndpoint(issuer, revocationEndpoint, "revocation");
      const body = new URLSearchParams({
        client_id: clientId,
        token: existing.refreshToken,
        token_type_hint: "refresh_token",
      });
      const response = await fetcher(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
        body,
        cache: "no-store",
        redirect: "error",
      });
      if (!response.ok) throw new Error("OIDC revocation was rejected");
    }
  } finally {
    await store.clear();
  }
}

function assertTrustedEndpoint(
  issuer: string,
  endpoint: string,
  endpointKind: "token" | "revocation",
): URL {
  const issuerUrl = new URL(issuer);
  const endpointUrl = new URL(endpoint);
  const isLoopback = ["localhost", "127.0.0.1", "[::1]"].includes(
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
    throw new Error("OIDC issuer and endpoint must not contain credentials or fragments");
  }
  if (endpointUrl.origin !== issuerUrl.origin) {
    throw new Error(`OIDC ${endpointKind} endpoint must share the configured issuer origin`);
  }
  return endpointUrl;
}
