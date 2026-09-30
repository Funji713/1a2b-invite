"use strict";

const ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function validHost(input) {
  if (!input || input.length > 253 || input.includes("%")) return false;
  const host = input.toLowerCase();
  if (host.includes(":")) {
    if (!/^[0-9a-f:.]+$/.test(host)) return false;
    try {
      const parsed = new URL(`http://[${host}]/`);
      return parsed.hostname.startsWith("[") && parsed.hostname.endsWith("]");
    } catch { return false; }
  }
  if (/^[0-9.]+$/.test(host)) {
    const parts = host.split(".");
    return parts.length === 4 && parts.every(part => /^[0-9]{1,3}$/.test(part) && Number(part) <= 255);
  }
  return host.split(".").every(label => label.length >= 1 && label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label));
}

function parseInvite(search) {
  if (!search.startsWith("?") || search.length === 1) return null;
  const values = {};
  for (const pair of search.slice(1).split("&")) {
    const separator = pair.indexOf("=");
    if (separator < 1 || separator !== pair.lastIndexOf("=")) return null;
    const key = pair.slice(0, separator);
    const raw = pair.slice(separator + 1);
    if (!/^(?:[^%]|%[0-9a-fA-F]{2})*$/.test(raw)) return null;
    if (!(["host", "port", "room"].includes(key)) || Object.hasOwn(values, key)) return null;
    try { values[key] = decodeURIComponent(raw); } catch { return null; }
  }
  if (Object.keys(values).length !== 3) return null;
  const host = values.host.toLowerCase();
  const port = values.port;
  const room = values.room;
  if (!validHost(host) || !/^[0-9]+$/.test(port) || Number(port) < 1 || Number(port) > 65535) return null;
  if (room.length !== 5 || ![...room].every(letter => ROOM_ALPHABET.includes(letter))) return null;
  const displayHost = host.includes(":") ? `[${host}]` : host;
  return {
    room,
    manual: `1A2B@${displayHost}:${Number(port)}/${room}`,
    deepLink: `onea2b://join?host=${encodeURIComponent(host)}&port=${Number(port)}&room=${room}`
  };
}

if (typeof module !== "undefined") module.exports = { parseInvite };

if (typeof document !== "undefined") {
  const invite = location.hash ? null : parseInvite(location.search);
  if (invite) {
    document.getElementById("valid").hidden = false;
    document.getElementById("room").textContent = invite.room;
    document.getElementById("manual").textContent = invite.manual;
    document.getElementById("open").addEventListener("click", () => { location.href = invite.deepLink; });
    document.getElementById("copy").addEventListener("click", async () => {
      const status = document.getElementById("copy-status");
      try {
        await navigator.clipboard.writeText(invite.manual);
        status.textContent = "邀請碼已複製。";
      } catch {
        status.textContent = "無法自動複製，請選取下方邀請碼並手動複製。";
      }
    });
  } else {
    document.getElementById("error").hidden = false;
  }
}
