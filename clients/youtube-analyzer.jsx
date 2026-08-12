import { useState, useRef, useEffect } from "react";

const FONT_URL = "https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap";
const link = document.createElement("link");
link.href = FONT_URL;
link.rel = "stylesheet";
document.head.appendChild(link);

const DEFAULT_API = "https://youtube-analyzer-api.onrender.com";

function Dots({ msg }) {
  return (
    <div style={{ textAlign: "center", padding: "20px 0" }}>
      <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 12 }}>
        {[0, 1, 2].map((i) => (
          <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: "#ff3e55", animation: `pulse 1.2s ease-in-out ${i * 0.2}s infinite` }} />
        ))}
      </div>
      <p style={{ color: "#aaa", fontSize: 13, fontFamily: "Outfit" }}>{msg}</p>
    </div>
  );
}

export default function YouTubeAnalyzerFull() {
  const [url, setUrl] = useState("");
  const [apiUrl, setApiUrl] = useState(() => {
    try { return window.localStorage?.getItem("yt-api-url") || DEFAULT_API; } catch { return DEFAULT_API; }
  });
  const [showSettings, setShowSettings] = useState(false);
  const [analysisMode, setAnalysisMode] = useState("smart"); // "smart" | "fast"
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const resultRef = useRef(null);
  const msgInterval = useRef(null);

  useEffect(() => {
    if (result && resultRef.current) resultRef.current.scrollIntoView({ behavior: "smooth" });
  }, [result]);

  useEffect(() => () => { if (msgInterval.current) clearInterval(msgInterval.current); }, []);

  const saveApiUrl = (v) => {
    setApiUrl(v);
    try { window.localStorage?.setItem("yt-api-url", v); } catch {}
  };

  const smartMsgs = [
    "서버를 깨우고 있어요... (첫 요청은 30초 걸릴 수 있어요)",
    "yt-dlp로 자막을 추출하고 있어요...",
    "AI가 자막을 분석하고 있어요...",
    "핵심 장면을 찾아서 자동 캡처 중...",
    "캡처한 화면을 AI가 분석하고 있어요...",
    "최종 리포트를 정리하고 있어요...",
    "거의 다 됐어요! 마무리 중...",
  ];
  const fastMsgs = [
    "서버를 깨우고 있어요...",
    "yt-dlp로 자막을 추출하고 있어요...",
    "AI가 자막을 분석하고 있어요...",
    "최종 리포트 정리 중...",
  ];

  const startMsgs = (msgs) => {
    let i = 0;
    setLoadingMsg(msgs[0]);
    msgInterval.current = setInterval(() => {
      i = Math.min(i + 1, msgs.length - 1);
      setLoadingMsg(msgs[i]);
    }, 8000);
  };
  const stopMsgs = () => { if (msgInterval.current) { clearInterval(msgInterval.current); msgInterval.current = null; } };

  const analyze = async () => {
    if (!url.trim()) { setError("YouTube URL을 입력해주세요."); return; }
    setError("");
    setResult(null);
    setLoading(true);

    const isSmart = analysisMode === "smart";
    startMsgs(isSmart ? smartMsgs : fastMsgs);

    try {
      const endpoint = isSmart ? "/api/analyze" : "/api/analyze-text";
      const base = apiUrl.replace(/\/+$/, "");
      const res = await fetch(`${base}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim(), capture_frames: true }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (e) {
      if (e.message.includes("Failed to fetch") || e.message.includes("NetworkError")) {
        setError("서버에 연결할 수 없습니다. API URL을 확인하거나, 서버가 슬립 상태일 수 있으니 30초 후 다시 시도해주세요.");
      } else {
        setError(`오류: ${e.message}`);
      }
    } finally {
      setLoading(false);
      stopMsgs();
    }
  };

  const reset = () => {
    setUrl(""); setResult(null); setError(""); setLoading(false); stopMsgs();
  };

  return (
    <div style={S.wrap}>
      <style>{`
        *{box-sizing:border-box;margin:0;padding:0}
        ::selection{background:#ff3e5544}
        textarea:focus,input:focus{outline:none;border-color:#ff3e5566!important}
        @keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
        @keyframes pulse{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}
        .ch:hover{transform:translateY(-1px);box-shadow:0 6px 24px rgba(255,62,85,.1)}
        button:hover{filter:brightness(1.08)}
      `}</style>

      {/* Header */}
      <div style={S.header}>
        <div style={S.logoRow}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="4" width="20" height="16" rx="4" fill="#ff3e55" />
            <polygon points="10,8 10,16 16,12" fill="#fff" />
          </svg>
          <span style={S.logo}>YouTube 완전 자동 분석기</span>
        </div>
        <p style={S.sub}>링크만 넣으면 자막 추출 → AI 분석 → 화면 캡처까지 전부 자동</p>
        <button style={{ ...S.btnTiny, marginTop: 8 }} onClick={() => setShowSettings(!showSettings)}>
          {showSettings ? "설정 닫기" : "⚙️ 서버 설정"}
        </button>
      </div>

      {/* Settings */}
      {showSettings && (
        <div style={{ ...S.card, animation: "fadeUp .3s ease" }}>
          <label style={S.label}>백엔드 API URL</label>
          <div style={S.row}>
            <input style={S.input} value={apiUrl} onChange={(e) => saveApiUrl(e.target.value)} placeholder="https://your-server.onrender.com" />
          </div>
          <p style={S.hint}>Render에 배포한 서버 URL을 입력하세요. README 참고.</p>
        </div>
      )}

      {/* Input */}
      {!result && !loading && (
        <div style={{ animation: "fadeUp .4s ease" }}>
          {/* Mode Toggle */}
          <div style={S.modeToggle}>
            <button style={{ ...S.modeBtn, ...(analysisMode === "smart" ? S.modeBtnOn : {}) }} onClick={() => setAnalysisMode("smart")}>
              🧠 스마트 분석
            </button>
            <button style={{ ...S.modeBtn, ...(analysisMode === "fast" ? S.modeBtnOn : {}) }} onClick={() => setAnalysisMode("fast")}>
              ⚡ 빠른 분석
            </button>
          </div>

          <div style={S.card} className="ch">
            <label style={S.label}>YouTube 링크</label>
            <div style={S.row}>
              <input style={S.input} placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && analyze()} />
              <button style={S.btn} onClick={analyze}>🔍 분석</button>
            </div>
            <div style={{ marginTop: 10, display: "flex", gap: 8, alignItems: "center" }}>
              {analysisMode === "smart" ? (
                <p style={S.hint}>자막 분석 + 핵심 장면 자동 캡처 + 화면 분석 (1~3분 소요, ~₩600)</p>
              ) : (
                <p style={S.hint}>자막만 분석 (30초~1분 소요, ~₩200)</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div style={{ ...S.card, animation: "fadeUp .3s ease" }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <span style={{ ...S.badge, background: analysisMode === "smart" ? "#ff3e5522" : "#1d9e7522", color: analysisMode === "smart" ? "#ff6b7a" : "#5DCAA5" }}>
              {analysisMode === "smart" ? "🧠 스마트 분석 진행 중" : "⚡ 빠른 분석 진행 중"}
            </span>
          </div>
          <Dots msg={loadingMsg} />
          <div style={{ background: "#0c0c15", borderRadius: 8, padding: "10px 14px", marginTop: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#666", fontFamily: "Outfit" }}>
              <span>자막 추출 → AI 분석{analysisMode === "smart" ? " → 프레임 캡처 → 화면 분석" : ""} → 리포트</span>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{ ...S.card, borderColor: "#ff3e5544", animation: "fadeUp .3s ease" }}>
          <p style={{ color: "#ff6b7a", fontSize: 14, fontFamily: "Outfit" }}>⚠️ {error}</p>
          <button style={{ ...S.btnSm, marginTop: 10 }} onClick={() => setError("")}>확인</button>
        </div>
      )}

      {/* Result */}
      {result && (
        <div style={{ animation: "fadeUp .4s ease" }}>
          {/* Video Info */}
          {result.video_info && (
            <div style={S.card} className="ch">
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                {result.video_info.thumbnail && (
                  <img src={result.video_info.thumbnail} alt="" style={S.thumb} />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 15, fontWeight: 600, color: "#e8e8ee", lineHeight: 1.4 }}>{result.video_info.title || "영상 분석 완료"}</p>
                  {result.video_info.author && <p style={{ fontSize: 12, color: "#777", marginTop: 2 }}>{result.video_info.author}</p>}
                  {result.video_info.duration > 0 && (
                    <p style={{ fontSize: 12, color: "#555", marginTop: 2 }}>
                      {Math.floor(result.video_info.duration / 60)}분 {result.video_info.duration % 60}초
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
            <div style={S.stat}>
              <div style={S.statLabel}>자막</div>
              <div style={S.statVal}>{result.stats?.subtitles_count || 0}개</div>
            </div>
            <div style={S.stat}>
              <div style={S.statLabel}>캡처 장면</div>
              <div style={S.statVal}>{result.stats?.frames_captured || 0}장</div>
            </div>
            <div style={S.stat}>
              <div style={S.statLabel}>예상 비용</div>
              <div style={S.statVal}>~₩{result.stats?.estimated_cost_krw || 0}</div>
            </div>
          </div>

          {/* Image analyses */}
          {result.image_analyses?.length > 0 && (
            <div style={S.card} className="ch">
              <span style={{ ...S.badge, background: "#ff3e5522", color: "#ff6b7a" }}>
                🖼️ 자동 캡처 + 화면 분석 ({result.image_analyses.length}장)
              </span>
              <div style={{ marginTop: 12 }}>
                {result.image_analyses.map((a, i) => (
                  <div key={i} style={{ background: "#0c0c15", border: "1px solid #1f1f32", borderRadius: 8, padding: 12, marginBottom: 8 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline", marginBottom: 6 }}>
                      <span style={{ fontFamily: "JetBrains Mono", fontSize: 12, color: "#ff6b7a", fontWeight: 500 }}>{a.timestamp}</span>
                      <span style={{ fontSize: 12, color: "#888" }}>{a.reason}</span>
                    </div>
                    <p style={{ fontSize: 13, color: "#bbb", lineHeight: 1.6 }}>{a.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Final Report */}
          {result.final_report && (
            <div ref={resultRef} style={{ ...S.card, borderColor: "#ff3e5533" }} className="ch">
              <span style={{ ...S.badge, background: "#ff3e5522", color: "#ff6b7a" }}>
                ✨ {analysisMode === "smart" ? "스마트" : "빠른"} 분석 완료
              </span>
              <div style={{ marginTop: 14, lineHeight: 1.8 }}>
                {result.final_report.split("\n").map((line, i) => {
                  if (line.match(/^[📌📝💡🎯🖼️]/)) return <h3 key={i} style={{ fontSize: 16, fontWeight: 700, color: "#f0f0f5", marginTop: 16, marginBottom: 8 }}>{line}</h3>;
                  if (line.trim().startsWith("-") || line.trim().startsWith("•")) return <p key={i} style={{ fontSize: 14, color: "#bbb", paddingLeft: 8, marginBottom: 4 }}>{line}</p>;
                  if (line.trim()) return <p key={i} style={{ fontSize: 14, color: "#bbb", marginBottom: 4 }}>{line}</p>;
                  return <div key={i} style={{ height: 6 }} />;
                })}
              </div>
            </div>
          )}

          {/* Reset */}
          <div style={{ textAlign: "center", marginTop: 10 }}>
            <button style={S.btnGhost} onClick={reset}>↺ 새로운 영상 분석하기</button>
          </div>
        </div>
      )}
    </div>
  );
}

const S = {
  wrap: { maxWidth: 640, margin: "0 auto", padding: "28px 16px", fontFamily: "Outfit, sans-serif", color: "#e8e8ee", minHeight: "100vh" },
  header: { textAlign: "center", marginBottom: 20 },
  logoRow: { display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginBottom: 6 },
  logo: { fontSize: 22, fontWeight: 700, letterSpacing: "-.5px", background: "linear-gradient(135deg,#ff3e55,#ff8a65)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" },
  sub: { fontSize: 13, color: "#777" },
  modeToggle: { display: "flex", gap: 4, marginBottom: 14, padding: 4, background: "#0c0c15", borderRadius: 12, border: "1px solid #1f1f32" },
  modeBtn: { flex: 1, padding: "9px 10px", border: "none", borderRadius: 10, background: "transparent", color: "#666", fontSize: 13, fontWeight: 600, fontFamily: "Outfit", cursor: "pointer", transition: "all .2s" },
  modeBtnOn: { background: "#1a1a2e", color: "#ff6b7a", boxShadow: "0 2px 8px rgba(255,62,85,.12)" },
  card: { background: "#13131f", border: "1px solid #1f1f32", borderRadius: 14, padding: 18, marginBottom: 12, transition: "all .25s" },
  label: { fontSize: 12, fontWeight: 600, color: "#888", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 8, display: "block" },
  row: { display: "flex", gap: 8 },
  input: { flex: 1, background: "#0c0c15", border: "1px solid #2a2a3a", borderRadius: 10, padding: "11px 14px", color: "#e8e8ee", fontSize: 13, fontFamily: "JetBrains Mono, monospace", transition: "border .2s" },
  hint: { fontSize: 11, color: "#555" },
  btn: { background: "linear-gradient(135deg,#ff3e55,#e62e45)", border: "none", borderRadius: 10, padding: "11px 18px", color: "#fff", fontSize: 13, fontWeight: 600, fontFamily: "Outfit", cursor: "pointer", whiteSpace: "nowrap" },
  btnGhost: { background: "transparent", border: "1px solid #2a2a3a", borderRadius: 10, padding: "9px 16px", color: "#999", fontSize: 12, fontWeight: 500, fontFamily: "Outfit", cursor: "pointer" },
  btnSm: { background: "#1a1a2e", border: "1px solid #2a2a3a", borderRadius: 8, padding: "7px 12px", color: "#ccc", fontSize: 12, fontFamily: "Outfit", cursor: "pointer" },
  btnTiny: { background: "transparent", border: "none", color: "#555", fontSize: 12, fontFamily: "Outfit", cursor: "pointer", padding: "4px 8px" },
  badge: { fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 20, letterSpacing: ".2px" },
  thumb: { width: 100, height: 56, borderRadius: 6, objectFit: "cover", background: "#1a1a2a", flexShrink: 0 },
  stat: { background: "#0c0c15", borderRadius: 10, padding: "12px 14px", textAlign: "center" },
  statLabel: { fontSize: 11, color: "#666", marginBottom: 4, fontFamily: "Outfit" },
  statVal: { fontSize: 16, fontWeight: 600, color: "#e8e8ee", fontFamily: "JetBrains Mono" },
};
