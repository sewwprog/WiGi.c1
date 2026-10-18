import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2.76.1";

const db = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { autoRefreshToken: false, persistSession: false } }
);
const headers = {
  "Content-Type": "application/json",
  "Cache-Control": "no-store",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
};
const origins = new Set(["https://sewwprog.github.io", "http://localhost:3000", "http://localhost:5500", "http://127.0.0.1:5500"]);

const json = (status: number, body: Record<string, string | boolean>, origin: string) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...headers, ...(origins.has(origin) ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : {}) }
  });

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  if (req.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: { ...headers, ...(origins.has(origin) ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : {}) }
    });
  }
  if (req.method !== "POST") return json(405, { error: "Method not allowed" }, origin);
  if (origin && !origins.has(origin)) return json(403, { error: "Origin not allowed" }, origin);

  try {
    if (Number(req.headers.get("content-length") || "0") > 2048) {
      return json(413, { error: "Request too large" }, origin);
    }
    const raw = await req.text();
    if (raw.length > 2048) return json(413, { error: "Request too large" }, origin);
    const payload = JSON.parse(raw);
    const nickname = String(payload.username || "").trim().toLowerCase();
    const password = String(payload.password || "");

    if (!/^[a-z][a-z0-9_]{2,19}$/.test(nickname)) {
      return json(400, { error: "Некоректний логін." }, origin);
    }
    const isInitialAdmin = nickname === "sewapro";
    const activationCode = String(payload.activationCode || "").trim().toLowerCase();
    if (isInitialAdmin && !/^[0-9a-f]{48}$/.test(activationCode)) {
      return json(403, { error: "Для SeWapro потрібен код активації." }, origin);
    }
    if (isInitialAdmin && password.length < 12) {
      return json(400, { error: "Для адміністратора потрібен пароль від 12 символів." }, origin);
    }
    if (password.length < 8 || password.length > 128) {
      return json(400, { error: "Пароль має містити від 8 до 128 символів." }, origin);
    }
    if (/^(.{1,4})\1{2,}$/.test(password) || password.toLowerCase().includes(nickname)) {
      return json(400, { error: "Пароль занадто передбачуваний." }, origin);
    }

    // Protect the public admin.createUser endpoint against bursts.
    // Hash request IP so the database never keeps raw IP addresses.
    const forwarded = req.headers.get("x-forwarded-for") || "";
    const ip = (req.headers.get("x-real-ip") || forwarded.split(",")[0] || "unknown").trim().slice(0, 100);
    const encoder = new TextEncoder();
    const hash = await crypto.subtle.digest("SHA-256", encoder.encode(Deno.env.get("SUPABASE_URL") + ":" + ip));
    const ipHash = [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, "0")).join("");
    const { data: allowed, error: rateError } = await db.rpc("sl2_signup_quota", { bucket_hash: ipHash });
    if (rateError) {
      console.error("Signup quota failure", rateError.code);
      return json(503, { error: "Реєстрація тимчасово недоступна." }, origin);
    }
    if (!allowed) return json(429, { error: "Забагато спроб реєстрації. Спробуй пізніше." }, origin);

    const { data, error } = await db.auth.admin.createUser({
      email: nickname + "@stoneland.invalid",
      password,
      email_confirm: true,
      ...(isInitialAdmin ? { user_metadata: { sl2_activation: activationCode } } : {})
    });
    if (error) {
      if (isInitialAdmin && /database error|activation|reserved/i.test(error.message || "")) {
        return json(403, { error: "Код активації неправильний, уже використаний або прострочений." }, origin);
      }
      if (/already registered|already exists|duplicate/i.test(error.message || "")) {
        return json(409, { error: "Цей логін уже зайнятий." }, origin);
      }
      console.error("User registration failed", error.status, error.code);
      return json(400, { error: "Не вдалося створити акаунт. Спробуй інший логін чи пароль." }, origin);
    }
    // Once consumed in the insert trigger, clear the one-time code from Auth user metadata.
    if (isInitialAdmin && data?.user?.id) {
      await db.auth.admin.updateUserById(data.user.id, { user_metadata: {} });
    }
    return json(201, { ok: true }, origin);
  } catch (e) {
    console.error("Unexpected signup error", String(e));
    return json(400, { error: "Не вдалося обробити реєстрацію." }, origin);
  }
});
