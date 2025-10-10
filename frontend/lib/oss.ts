import OSS from 'ali-oss';

export function createOssClient() {
  const region = process.env.ALI_OSS_REGION;
  const accessKeyId = process.env.ALI_OSS_ACCESS_KEY_ID;
  const accessKeySecret = process.env.ALI_OSS_ACCESS_KEY_SECRET;
  const bucket = process.env.ALI_OSS_BUCKET;
  if (!region || !accessKeyId || !accessKeySecret || !bucket) {
    throw new Error('OSS env missing: ALI_OSS_REGION/ALI_OSS_ACCESS_KEY_ID/ALI_OSS_ACCESS_KEY_SECRET/ALI_OSS_BUCKET');
  }
  return new OSS({ region, accessKeyId, accessKeySecret, bucket });
}

export async function uploadBufferToOss(params: { buffer: Buffer; key: string; mime?: string; headers?: Record<string, string>; }) {
  const client = createOssClient();
  const { buffer, key, mime, headers } = params;
  const res = await client.put(key, buffer, { headers: { 'Content-Type': mime || 'application/octet-stream', ...(headers || {}) } });
  const publicEndpoint = process.env.ALI_OSS_PUBLIC_ENDPOINT;
  const url = publicEndpoint ? `${publicEndpoint.replace(/\/$/, '')}/${encodeURI(key)}` : (res.url || res.name);
  return { key, url, etag: res.etag };
}

export function buildAudioObjectKey(filename: string) {
  const prefix = (process.env.ALI_OSS_PREFIX || 'audio/').replace(/^\/+|\/+$/g, '') + '/';
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, '0');
  const d = String(now.getUTCDate()).padStart(2, '0');
  const ts = now.getTime();
  const safeName = filename.replace(/[^a-zA-Z0-9_.-]/g, '_');
  return `${prefix}${y}/${m}/${d}/${ts}-${safeName}`;
}
export function buildObjectKey(filename: string, category?: 'images' | 'audio' | 'pdf' | 'files') {
  const cat = (category || 'files');
  const basePrefix = process.env.ALI_OSS_PREFIX || '';
  const prefix = [basePrefix.replace(/^\/+|\/+$/g, ''), cat].filter(Boolean).join('/') + '/';
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, '0');
  const d = String(now.getUTCDate()).padStart(2, '0');
  const ts = now.getTime();
  const safeName = filename.replace(/[^a-zA-Z0-9_.-]/g, '_');
  return `${prefix}${y}/${m}/${d}/${ts}-${safeName}`;
}

// Generate a signed GET URL for private buckets
export async function signGetUrl(params: { key: string; expiresSec?: number; response?: Record<string, string> }) {
  const client = createOssClient();
  const { key, expiresSec, response } = params;
  const expires = typeof expiresSec === 'number' && expiresSec > 0 ? expiresSec : 600; // default 10 min
  const url = client.signatureUrl(key, {
    method: 'GET',
    expires,
    response, // e.g., { 'response-content-disposition': 'inline' }
  });
  const expiresAt = Date.now() + expires * 1000;
  return { url, expiresAt };
}
