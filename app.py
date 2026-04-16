import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
from io import BytesIO
from PIL import Image
from datetime import datetime
import json
import base64
import anthropic

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ad Creative Audit Agent",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .section-header {
    background: #1e293b;
    color: #fff;
    padding: 10px 16px;
    border-radius: 8px;
    font-weight: 700;
    margin: 24px 0 10px 0;
    font-size: 1em;
    letter-spacing: 0.3px;
  }
  .verdict-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    margin: 12px 0;
    font-style: italic;
    color: #475569;
    font-size: 1.05em;
  }
  .fix-item {
    background: #fff5f5;
    border-left: 4px solid #ef4444;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin: 6px 0;
    color: #1e293b;
  }
  .strength-item {
    background: #f0fdf4;
    border-left: 4px solid #22c55e;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin: 6px 0;
    color: #1e293b;
  }
  .score-row {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #f1f5f9;
  }
  .badge {
    min-width: 52px;
    text-align: center;
    border-radius: 8px;
    padding: 6px 4px;
    font-weight: 800;
    font-size: 1.3em;
    line-height: 1;
    flex-shrink: 0;
  }
  .badge-label {
    font-size: 0.6em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: block;
    margin-top: 2px;
  }
  .stButton > button[kind="primary"] {
    background: #3b82f6;
    color: white;
    border: none;
    font-weight: 700;
    padding: 12px;
  }
</style>
""", unsafe_allow_html=True)

# ─── Constants ────────────────────────────────────────────────────────────────
SCORE_COLOR = {5: "#22c55e", 4: "#84cc16", 3: "#eab308", 2: "#f97316", 1: "#ef4444", 0: "#94a3b8"}
SCORE_LABEL = {5: "Excellent", 4: "Good", 3: "Average", 2: "Poor", 1: "Critical", 0: "N/A"}

CHECKLIST = [
    {"id": "hook_click",   "section": "1. Hook Strength",              "label": "Hook",             "desc": "Would YOU actually click on this ad if you were the target audience? Be honest.",             "visual": False},
    {"id": "hook_angle",   "section": "1. Hook Strength",              "label": "Angle",            "desc": "Is there one main message/angle only, and is it actually convincing?",                       "visual": False},
    {"id": "brand_align",  "section": "2. Brand Voice",                "label": "Brand Alignment",  "desc": "Do the language, words, colours and style match the client's brand?",                        "visual": True},
    {"id": "client_req",   "section": "2. Brand Voice",                "label": "Client Requirements","desc": "Have we satisfied ALL client rules, asks and requirements?",                               "visual": False},
    {"id": "visual_hier",  "section": "3. Ad Quality — Creative",      "label": "Visual Hierarchy", "desc": "Are visual hierarchy principles satisfied? Elements balanced? No cramped layouts?",           "visual": True},
    {"id": "spacing",      "section": "3. Ad Quality — Creative",      "label": "Spacing",          "desc": "Is spacing BALANCED?",                                                                       "visual": True},
    {"id": "readability",  "section": "3. Ad Quality — Creative",      "label": "Readability",      "desc": "F-Shape reading pattern followed? Text easy to read against background?",                    "visual": True},
    {"id": "mobile",       "section": "3. Ad Quality — Creative",      "label": "Mobile Friendly",  "desc": "If viewed on mobile, can you read it clearly?",                                              "visual": True},
    {"id": "format",       "section": "3. Ad Quality — Creative",      "label": "Format",           "desc": "Correct ratios (1:1 or 4:5 for Feed, 9:16 for Stories/Reels)? Safe zones respected?",       "visual": True},
    {"id": "hygiene",      "section": "3. Ad Quality — Creative",      "label": "Hygiene",          "desc": 'No typos. Reads well. "Title Case" used for headlines.',                                     "visual": True},
    {"id": "video_hook",   "section": "3a. Ad Quality — Video",        "label": "Video Hook",       "desc": "Is the first 3 seconds visually startling or highly engaging to stop the scroll?",          "visual": True},
    {"id": "sound_off",    "section": "3a. Ad Quality — Video",        "label": "Sound-Off Friendly","desc": "Does the video make sense without sound? Are there captions/overlays?",                     "visual": True},
    {"id": "pacing",       "section": "3a. Ad Quality — Video",        "label": "Pacing",           "desc": "Is editing fast enough? No long pauses. Every ~3 seconds, some kind of movement.",           "visual": True},
    {"id": "text_hook",    "section": "4. Primary Text & Headlines",   "label": "Hook",             "desc": "Does the primary text start with a strong hook or question?",                                "visual": False},
    {"id": "usps",         "section": "4. Primary Text & Headlines",   "label": "USPs",             "desc": "Are the USPs clear? Did you use numbers/symbols ($, %, +) to catch the eye?",               "visual": False},
    {"id": "clarity",      "section": "4. Primary Text & Headlines",   "label": "Clarity",          "desc": "Is it written at a 5th-grade reading level?",                                               "visual": False},
]

ECOMMERCE_CONTEXT = """
For ECOMMERCE accounts, weight these heavily:
- Product clarity — can you tell what's being sold in under 2 seconds?
- Benefit-led copy (not feature-led)
- Social proof signals (reviews, numbers, testimonials)
- Clear offer/price anchoring
- Strong CTA driving to product or collection page
- Scroll-stopping visual with the product as the hero
"""

LEADGEN_CONTEXT = """
For LEAD GEN accounts, weight these heavily:
- Pain point clarity — does the ad speak directly to the prospect's problem?
- Value of the lead magnet/offer is crystal clear
- Low-friction language that reduces commitment anxiety
- Trust signals (qualifications, logos, social proof)
- CTA is specific about what happens next ("Get free quote", not just "Learn more")
- Right people should self-select in
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_sheet_id(url):
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return m.group(1) if m else None

def read_public_sheet(url):
    sheet_id = extract_sheet_id(url)
    if not sheet_id:
        return None, "Invalid Google Sheets URL."
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df = pd.read_csv(csv_url).dropna(how="all")
        return df, None
    except Exception:
        return None, "Could not read sheet. Make sure sharing is set to 'Anyone with the link can view'."

def get_canva_preview(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            img_resp = requests.get(og["content"], headers=headers, timeout=12)
            return Image.open(BytesIO(img_resp.content)), None
        return None, "Could not auto-fetch Canva preview — please upload a screenshot."
    except Exception as e:
        return None, f"Could not fetch Canva preview: {e}"

def image_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

def build_checklist_text():
    out, section = "", ""
    for item in CHECKLIST:
        if item["section"] != section:
            section = item["section"]
            out += f"\n### {section}\n"
        out += f'- **{item["id"]}** ({item["label"]}): {item["desc"]}\n'
    return out

def build_system_prompt(account_type, platform):
    context = ECOMMERCE_CONTEXT if account_type == "Ecommerce" else LEADGEN_CONTEXT
    return f"""You are a senior paid media creative auditor specialising in {platform} advertising for {account_type} businesses.

You audit ad creatives against a structured checklist and return strict, honest JSON scorecards.

{context}

Scoring scale:
- 5 = Excellent — best practice, publish-ready
- 4 = Good — minor improvements possible
- 3 = Average — clear room for improvement
- 2 = Poor — significant issue, likely hurts performance
- 1 = Critical — must fix before going live

Be strict and honest. A 4 or 5 must be earned. Do not give 5s by default.
For video-specific items (video_hook, sound_off, pacing): if the creative is a static image, score them 0 and rationale "N/A — static image".
Return ONLY valid JSON, no markdown fences, no explanation outside the JSON."""

def build_user_message(ad_data, canva_url, has_image):
    copy_lines = "\n".join(f"  - **{k}**: {v}" for k, v in ad_data.items() if v and str(v).strip() not in ("", "nan"))
    ids = [item["id"] for item in CHECKLIST]
    empty = ",\n    ".join(f'"{i}": {{"score": 0, "rationale": "..."}}' for i in ids)
    image_note = "[A screenshot of the Canva creative is attached — analyse it visually for all creative/visual criteria.]" if has_image else f"[Canva link: {canva_url} — analyse the visual as best you can from context.]"

    return f"""Please audit this ad creative:

**AD COPY:**
{copy_lines}

**CREATIVE:**
{image_note}

**CHECKLIST:**
{build_checklist_text()}

Return ONLY this JSON (no markdown, no text before or after):

{{
  "scores": {{
    {empty}
  }},
  "overall_score": 0,
  "priority_fixes": ["Fix 1", "Fix 2", "Fix 3"],
  "strengths": ["Strength 1", "Strength 2"],
  "ready_to_publish": false,
  "one_line_verdict": "One honest sentence summary."
}}"""

def run_audit(api_key, account_type, platform, ad_data, image: Image.Image, canva_url):
    client = anthropic.Anthropic(api_key=api_key)
    has_image = image is not None
    system = build_system_prompt(account_type, platform)
    user_text = build_user_message(ad_data, canva_url, has_image)

    content = []
    if has_image:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_to_base64(image),
            }
        })
    content.append({"type": "text", "text": user_text})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.content[0].text.strip()
    # strip markdown fences if Claude adds them
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)

# ─── Render Scorecard ─────────────────────────────────────────────────────────

def render_scorecard(results, account_type, platform, ad_data):
    scores = results.get("scores", {})
    overall = int(results.get("overall_score", 0))
    fixes = [f for f in results.get("priority_fixes", []) if f and f != "..."]
    strengths = [s for s in results.get("strengths", []) if s and s != "..."]
    ready = results.get("ready_to_publish", False)
    verdict = results.get("one_line_verdict", "")

    oc = SCORE_COLOR.get(overall, "#94a3b8")
    ready_color = "#22c55e" if ready else "#ef4444"
    ready_text  = "✅ Ready to Publish" if ready else "🚫 Not Ready to Publish"

    # Overall
    st.markdown("## Audit Results")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"""
        <div style="border:3px solid {oc}; border-radius:14px; padding:28px;
                    text-align:center; background:{oc}12">
          <div style="font-size:3.8em; font-weight:900; color:{oc}; line-height:1">{overall}/5</div>
          <div style="font-size:0.95em; color:#64748b; margin:6px 0">Overall Creative Score</div>
          <div style="font-weight:700; color:{ready_color}; font-size:1em">{ready_text}</div>
          <div style="color:#64748b; font-size:0.85em; margin-top:10px; font-style:italic">
            "{verdict}"
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Scorecard rows by section
    current_section = ""
    for item in CHECKLIST:
        if item["section"] != current_section:
            current_section = item["section"]
            st.markdown(f'<div class="section-header">{current_section}</div>', unsafe_allow_html=True)

        score_data = scores.get(item["id"], {})
        score = score_data.get("score", 0)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0
        rationale = score_data.get("rationale", "—")

        c = SCORE_COLOR.get(score, "#94a3b8")
        lbl = SCORE_LABEL.get(score, "N/A")

        col1, col2, col3 = st.columns([2, 1, 4])
        with col1:
            st.markdown(f"**{item['label']}**")
            st.caption(item["desc"])
        with col2:
            st.markdown(f"""
            <div style="background:{c}15; border:2px solid {c}; border-radius:8px;
                        padding:10px 6px; text-align:center">
              <div style="font-size:1.8em; font-weight:900; color:{c}; line-height:1">{score}</div>
              <div style="font-size:0.6em; color:{c}; font-weight:700;
                          text-transform:uppercase; letter-spacing:0.5px">{lbl}</div>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            st.markdown(f"<div style='padding-top:8px; color:#334155; line-height:1.5'>{rationale}</div>",
                        unsafe_allow_html=True)

        st.markdown("")  # spacer

    st.markdown("---")

    # Fixes + Strengths
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🔴 Priority Fixes")
        for f in fixes:
            st.markdown(f'<div class="fix-item">{f}</div>', unsafe_allow_html=True)
    with col2:
        st.markdown("### 🟢 Strengths")
        for s in strengths:
            st.markdown(f'<div class="strength-item">{s}</div>', unsafe_allow_html=True)


def generate_html_report(results, account_type, platform, ad_data, canva_url):
    scores   = results.get("scores", {})
    overall  = int(results.get("overall_score", 0))
    fixes    = [f for f in results.get("priority_fixes", []) if f and f != "..."]
    strengths= [s for s in results.get("strengths", []) if s and s != "..."]
    ready    = results.get("ready_to_publish", False)
    verdict  = results.get("one_line_verdict", "")
    now      = datetime.now().strftime("%B %d, %Y at %H:%M")
    oc       = SCORE_COLOR.get(overall, "#94a3b8")
    rc       = "#22c55e" if ready else "#ef4444"
    rt       = "Ready to Publish" if ready else "Not Ready to Publish"

    rows = ""
    for item in CHECKLIST:
        sd    = scores.get(item["id"], {})
        score = int(sd.get("score", 0)) if sd.get("score") else 0
        rat   = sd.get("rationale", "")
        c     = SCORE_COLOR.get(score, "#94a3b8")
        lbl   = SCORE_LABEL.get(score, "N/A")
        rows += f"""<tr>
          <td style="padding:10px;border-bottom:1px solid #f1f5f9;color:#64748b;font-size:.85em">{item['section']}</td>
          <td style="padding:10px;border-bottom:1px solid #f1f5f9"><strong>{item['label']}</strong><br>
              <span style="color:#94a3b8;font-size:.8em">{item['desc']}</span></td>
          <td style="padding:10px;border-bottom:1px solid #f1f5f9;text-align:center">
              <span style="background:{c}20;border:2px solid {c};border-radius:6px;
                           padding:4px 10px;font-weight:800;color:{c}">{score}/5</span><br>
              <span style="color:{c};font-size:.75em">{lbl}</span></td>
          <td style="padding:10px;border-bottom:1px solid #f1f5f9;color:#475569;font-size:.9em">{rat}</td>
        </tr>"""

    ad_rows = "".join(
        f"<tr><td style='padding:6px 10px;font-weight:600;color:#374151;border-bottom:1px solid #f1f5f9'>{k}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #f1f5f9;color:#475569'>{v}</td></tr>"
        for k, v in ad_data.items() if v and str(v).strip() not in ("", "nan")
    )
    fix_items      = "".join(f"<li style='margin:6px 0'>{f}</li>" for f in fixes)
    strength_items = "".join(f"<li style='margin:6px 0'>{s}</li>" for s in strengths)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Ad Creative Audit Report</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       margin:0;padding:40px;color:#1e293b;background:#f8fafc}}
  .container{{max-width:920px;margin:0 auto;background:#fff;border-radius:16px;
              padding:40px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
  h1{{color:#0f172a;border-bottom:3px solid #3b82f6;padding-bottom:12px}}
  h2{{color:#1e293b;margin-top:32px}}
  table{{width:100%;border-collapse:collapse;margin:16px 0}}
  th{{background:#f1f5f9;padding:10px 12px;text-align:left;font-size:.85em;
      text-transform:uppercase;letter-spacing:.5px;color:#64748b}}
  .meta{{color:#64748b;font-size:.9em;margin-bottom:24px}}
  .overall{{display:inline-block;padding:24px 48px;border:3px solid {oc};
            border-radius:14px;text-align:center;background:{oc}10}}
  @media print{{body{{background:white}}.container{{box-shadow:none}}}}
</style></head>
<body><div class="container">
  <h1>📋 Ad Creative Audit Report</h1>
  <div class="meta">Generated: {now} &nbsp;|&nbsp; Platform: {platform} &nbsp;|&nbsp; Type: {account_type}</div>
  <h2>Overall Score</h2>
  <div class="overall">
    <div style="font-size:3em;font-weight:900;color:{oc};line-height:1">{overall}/5</div>
    <div style="color:#64748b;margin:4px 0">Overall Creative Score</div>
    <div style="color:{rc};font-weight:700;margin-top:8px">{rt}</div>
    <div style="font-style:italic;color:#475569;margin-top:8px">&ldquo;{verdict}&rdquo;</div>
  </div>
  <h2>Ad Copy</h2>
  <table><tbody>{ad_rows}</tbody></table>
  <h2>Detailed Scorecard</h2>
  <table><thead><tr>
    <th>Section</th><th>Criteria</th>
    <th style="text-align:center">Score</th><th>Rationale</th>
  </tr></thead><tbody>{rows}</tbody></table>
  <div style="display:flex;gap:32px;margin-top:32px">
    <div style="flex:1;background:#fff5f5;border-radius:10px;padding:20px">
      <h2 style="margin-top:0">🔴 Priority Fixes</h2><ul>{fix_items}</ul>
    </div>
    <div style="flex:1;background:#f0fdf4;border-radius:10px;padding:20px">
      <h2 style="margin-top:0">🟢 Strengths</h2><ul>{strength_items}</ul>
    </div>
  </div>
  <p style="margin-top:40px;color:#94a3b8;font-size:.8em;border-top:1px solid #f1f5f9;padding-top:16px">
    Canva: {canva_url}<br>Ad Creative Audit Agent — Matriarch Digital
  </p>
</div></body></html>"""


# ─── App ──────────────────────────────────────────────────────────────────────

def main():
    # Load API key from Streamlit secrets
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        st.error("❌ API key not configured. Add ANTHROPIC_API_KEY to your Streamlit secrets.")
        st.stop()

    with st.sidebar:
        st.markdown("## ⚙️ Settings")
        platform     = st.selectbox("Ad Platform", ["Meta Ads", "Google Ads"])
        account_type = st.selectbox("Account Type", ["Ecommerce", "Lead Gen"])
        st.markdown("---")
        st.markdown("**How to use:**")
        st.markdown("""
1. Select platform & account type
2. Paste Google Sheet URL
3. Paste Canva share link
4. Click **Run Audit**
5. Download your report
        """)
        st.markdown("---")
        st.caption("Matriarch Digital — Ad Creative Audit Agent")

    st.title("📋 Ad Creative Audit Agent")
    st.caption("Automated creative auditing powered by Claude AI")

    st.markdown("---")

    # ── Inputs ────────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 📊 Google Sheet (Ad Copy)")
        sheet_url = st.text_input("Sheet URL",
                                  placeholder="https://docs.google.com/spreadsheets/d/...",
                                  label_visibility="collapsed")
    with col2:
        st.markdown("### 🎨 Canva Creative")
        canva_url = st.text_input("Canva Share Link",
                                  placeholder="https://www.canva.com/design/...",
                                  label_visibility="collapsed")

    # ── Load Sheet ────────────────────────────────────────────────────────────
    df        = None
    ad_data   = {}
    row_index = 0

    if sheet_url:
        with st.spinner("Reading sheet..."):
            df, err = read_public_sheet(sheet_url)
        if err:
            st.error(f"❌ {err}")
        elif df is not None:
            st.success(f"✅ Sheet loaded — {len(df)} row(s)")
            with st.expander("Preview sheet data", expanded=False):
                st.dataframe(df, use_container_width=True)
            if len(df) > 1:
                row_index = st.selectbox(
                    "Which ad to audit?",
                    range(len(df)),
                    format_func=lambda i: f"Row {i+1}: {str(df.iloc[i, 0])[:70]}"
                )
            row     = df.iloc[row_index]
            ad_data = {
                col: str(row[col])
                for col in df.columns
                if pd.notna(row[col]) and str(row[col]).strip() not in ("", "nan")
            }

    # ── Load Canva ────────────────────────────────────────────────────────────
    canva_image = None

    if canva_url:
        with st.spinner("Fetching Canva preview..."):
            canva_image, err = get_canva_preview(canva_url)
        if err:
            st.warning(f"⚠️ {err}")
            uploaded = st.file_uploader("Upload creative screenshot instead",
                                        type=["png", "jpg", "jpeg"])
            if uploaded:
                canva_image = Image.open(uploaded)
                st.success("✅ Screenshot uploaded")
        if canva_image:
            st.image(canva_image, caption="Creative Preview", use_column_width=True)

    st.markdown("---")

    # ── Run Audit Button ──────────────────────────────────────────────────────
    can_audit = bool(api_key) and bool(ad_data)

    if not can_audit:
        if not sheet_url:
            st.info("Paste your Google Sheet URL above to begin.")
    else:
        if st.button("⚡ Run Audit", type="primary", use_container_width=True):
            with st.spinner("Claude is auditing your creative — this takes 15–30 seconds..."):
                try:
                    results = run_audit(api_key, account_type, platform,
                                        ad_data, canva_image, canva_url or "")
                    st.session_state["results"]      = results
                    st.session_state["ad_data"]      = ad_data
                    st.session_state["account_type"] = account_type
                    st.session_state["platform"]     = platform
                    st.session_state["canva_url"]    = canva_url or ""
                    st.success("✅ Audit complete!")
                except anthropic.AuthenticationError:
                    st.error("❌ Invalid API key. Check your key at console.anthropic.com")
                except json.JSONDecodeError as e:
                    st.error(f"❌ Claude returned unexpected output. Try again. ({e})")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── Results ───────────────────────────────────────────────────────────────
    if "results" in st.session_state:
        st.markdown("---")
        render_scorecard(
            st.session_state["results"],
            st.session_state.get("account_type", account_type),
            st.session_state.get("platform", platform),
            st.session_state.get("ad_data", ad_data),
        )

        st.markdown("---")
        st.markdown("### 📄 Download Report")
        html = generate_html_report(
            st.session_state["results"],
            st.session_state.get("account_type", account_type),
            st.session_state.get("platform", platform),
            st.session_state.get("ad_data", ad_data),
            st.session_state.get("canva_url", ""),
        )
        st.download_button(
            "⬇️ Download HTML Report",
            data=html,
            file_name=f"audit_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
            mime="text/html",
            type="primary",
            use_container_width=True
        )
        st.caption("Open the .html file in any browser → File → Print → Save as PDF")


if __name__ == "__main__":
    main()
