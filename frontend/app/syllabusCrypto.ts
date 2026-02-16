/**
 * Client-side syllabus encryption (zero-knowledge).
 * Server never sees plaintext. UDK encrypted with KEK derived from password.
 */

// Type helper for Web Crypto BufferSource (avoids ArrayBufferLike strictness)
const toBuf = (arr: Uint8Array): ArrayBuffer =>
  new Uint8Array(arr).buffer;

const PBKDF2_ITERATIONS = 100000;
const SALT_LEN = 16;
const IV_LEN = 12;
const TAG_LEN = 16;
const KEY_LEN = 32;

function buf2b64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
    binary += String.fromCharCode.apply(null, Array.from(chunk));
  }
  return btoa(binary);
}

function b642buf(b64: string): ArrayBuffer {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

/** Derive KEK from password using PBKDF2. */
async function deriveKek(
  password: string,
  salt: Uint8Array,
  iterations: number
): Promise<CryptoKey> {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    enc.encode(password),
    "PBKDF2",
    false,
    ["deriveBits", "deriveKey"]
  );
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: toBuf(salt),
      iterations,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

/** Generate random UDK (32 bytes). */
function generateUdk(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(KEY_LEN));
}

/** Encrypt data with AES-256-GCM. */
async function encryptGcm(
  key: CryptoKey,
  data: ArrayBuffer,
  iv?: Uint8Array
): Promise<{ ciphertext: ArrayBuffer; iv: Uint8Array }> {
  const ivBytes = iv ?? crypto.getRandomValues(new Uint8Array(IV_LEN));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: toBuf(ivBytes), tagLength: TAG_LEN * 8 },
    key,
    data
  );
  return { ciphertext, iv: ivBytes };
}

/** Import raw key for AES-GCM. */
async function importAesKey(raw: ArrayBuffer): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    raw,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"]
  );
}

export interface EncryptResult {
  ciphertext: ArrayBuffer;
  wrappedUdk: ArrayBuffer;
  kdfParams: { salt: string; iterations: number };
}

/** Encrypt file with UDK, wrap UDK with KEK from password. */
export async function encryptSyllabus(
  fileContent: ArrayBuffer,
  password: string
): Promise<EncryptResult> {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LEN));
  const kek = await deriveKek(password, salt, PBKDF2_ITERATIONS);
  const udk = generateUdk();
  const udkKey = await importAesKey(toBuf(udk));

  const { ciphertext } = await encryptGcm(udkKey, fileContent);
  const { ciphertext: wrappedUdk } = await encryptGcm(kek, toBuf(udk));

  return {
    ciphertext,
    wrappedUdk,
    kdfParams: {
      salt: buf2b64(toBuf(salt)),
      iterations: PBKDF2_ITERATIONS,
    },
  };
}
