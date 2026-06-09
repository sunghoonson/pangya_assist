// pangya_memorial_sql_probe.js
// Memorial Coin 사용 시 GameServer가 DB로 보내는 SQL 필터링용
//
// 실행:
//   GameServer-01.exe 실행 후:
//   frida -n GameServer-01.exe -l .\pangya_memorial_sql_probe.js
//
// 그 다음 게임에서 Premium Memorial Coin 1~3개 사용.
// 콘솔의 [MEMORIAL_SQL] 로그를 저장해서 분석한다.

'use strict';

function now() {
    return new Date().toISOString().replace('T', ' ').replace('Z', '');
}

function log(s) {
    console.log(now() + ' ' + s);
}

function safeBytes(p, n) {
    try {
        const ab = ptr(p).readByteArray(n);
        if (ab === null) return null;
        return new Uint8Array(ab);
    } catch (e) {
        return null;
    }
}

function bytesToAscii(u8) {
    let s = "";
    for (let i = 0; i < u8.length; i++) {
        const c = u8[i];
        if (c === 0) s += ".";
        else if (c >= 32 && c <= 126) s += String.fromCharCode(c);
        else s += ".";
    }
    return s;
}

function bytesToHex(u8, maxLen) {
    const n = Math.min(u8.length, maxLen || u8.length);
    const out = [];
    for (let i = 0; i < n; i++) {
        out.push(("0" + u8[i].toString(16)).slice(-2).toUpperCase());
    }
    return out.join(" ");
}

function findExportAddress(name) {
    try {
        const m = Process.getModuleByName("ws2_32.dll");
        if (m && typeof m.getExportByName === "function") {
            return m.getExportByName(name);
        }
    } catch (e) {}

    try {
        const resolver = new ApiResolver("module");
        const matches = resolver.enumerateMatches("exports:ws2_32.dll!" + name);
        if (matches.length > 0) return matches[0].address;
    } catch (e) {}

    return null;
}

function isMemorialSqlText(s) {
    const lower = s.toLowerCase();
    return (
        lower.indexOf("memorial") >= 0 ||
        lower.indexOf("coin") >= 0 ||
        lower.indexOf("gacha") >= 0 ||
        lower.indexOf("gatcha") >= 0 ||
        lower.indexOf("lottery") >= 0 ||
        lower.indexOf("0x1a000272") >= 0 ||
        lower.indexOf("436208242") >= 0 ||
        lower.indexOf("usp_add_item") >= 0
    );
}

const sendAddr = findExportAddress("send");
if (sendAddr === null) {
    log("[ERR] ws2_32!send not found");
} else {
    Interceptor.attach(sendAddr, {
        onEnter(args) {
            this.sock = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave(retval) {
            try {
                const rv = retval.toInt32();
                let n = this.len;
                if (rv > 0 && rv < n) n = rv;
                if (n <= 0 || n > 8192) return;

                const u8 = safeBytes(this.buf, n);
                if (u8 === null) return;

                const ascii = bytesToAscii(u8);
                if (!isMemorialSqlText(ascii)) return;

                log("[MEMORIAL_SQL] sock=" + this.sock + " len=" + n);
                log("[MEMORIAL_SQL_ASCII] " + ascii);
                log("[MEMORIAL_SQL_HEX] " + bytesToHex(u8, 512));
            } catch (e) {
                log("[ERR] " + e);
            }
        }
    });
    log("[HOOK] ws2_32!send " + sendAddr + " OK");
}

log("[READY] Memorial SQL probe loaded. Use 1~3 Premium Memorial Coins now.");
