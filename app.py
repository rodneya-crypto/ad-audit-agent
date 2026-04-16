import streamlit as st
import pandas as pd
import requests
import re
from io import BytesIO
from PIL import Image
from datetime import datetime
import json
import base64
import anthropic
import os

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
    background: #1e293b; color: #fff;
    padding: 10px 16px; border-radius: 8px;
    font-weight: 700; margin: 24px 0 10px 0;
    font-size: 1em; letter-spacing: 0.3px;
  }
  .fix-item {
    background: #fff5f5; border-left: 4px solid #ef4444;
    padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 6px 0;
  }
  .strength-item {
    background: #f0fdf4; border-left: 4px solid #22c55e;
    padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 6px 0;
  }
  .copy-preview {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 10px; padding: 16px; margin: 8px 0;
  }
  .copy-label {
    font-size: 0.75em; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; color: #64748b; margin-bottom: 4px;
  }
  .copy-value {
    color: #1e293b; font-size: 0.95em; line-height: 1.6;
  }
  .headline-item {
    background: #fff; border: 1px solid #e2e8f0;
    border-radius: 6px; padding: 6px 10px; margin: 3px 0;
    font-size: 0.9em; color: #334155;
  }
</style>
""", unsafe_allow_html=True)

# ─── Constants ────────────────────────────────────────────────────────────────
SCORE_COLOR = {5: "#22c55e", 4: "#84cc16", 3: "#eab308", 2: "#f97316", 1: "#ef4444", 0: "#94a3b8"}
SCORE_LABEL = {5: "Excellent", 4: "Good", 3: "Average", 2: "Poor", 1: "Critical", 0: "N/A"}
BRANDS_FILE = "brands.json"

FULL_CHECKLIST = [
    {"id": "hook_click",  "section": "1. Hook Strength",            "label": "Hook",              "desc": "Would YOU actually click on this ad if you were the target audience?",                    "type": "copy"},
    {"id": "hook_angle",  "section": "1. Hook Strength",            "label": "Angle",             "desc": "Is there one main message/angle only, and is it actually convincing?",                    "type": "copy"},
    {"id": "brand_align", "section": "2. Brand Voice",              "label": "Brand Alignment",   "desc": "Do language, words, colours and style match the client's brand?",                        "type": "both"},
    {"id": "client_req",  "section": "2. Brand Voice",              "label": "Client Requirements","desc": "Have we satisfied ALL client rules, asks and requirements?",                             "type": "both"},
    {"id": "visual_hier", "section": "3. Ad Quality — Creative",    "label": "Visual Hierarchy",  "desc": "Visual hierarchy principles satisfied? Elements balanced? No cramped layouts?",          "type": "visual"},
    {"id": "spacing",     "section": "3. Ad Quality — Creative",    "label": "Spacing",           "desc": "Is spacing BALANCED?",                                                                   "type": "visual"},
    {"id": "readability", "section": "3. Ad Quality — Creative",    "label": "Readability",       "desc": "F-Shape reading pattern followed? Text easy to read against background?",               "type": "visual"},
    {"id": "mobile",      "section": "3. Ad Quality — Creative",    "label": "Mobile Friendly",   "desc": "If viewed on mobile, can you read it clearly?",                                         "type": "visual"},
    {"id": "format",      "section": "3. Ad Quality — Creative",    "label": "Format",            "desc": "Correct ratios (1:1 or 4:5 for Feed, 9:16 for Stories/Reels)? Safe zones respected?",  "type": "visual"},
    {"id": "hygiene",     "section": "3. Ad Quality — Creative",    "label": "Hygiene",           "desc": 'No typos. Reads well. "Title Case" used for headlines.',                                "type": "visual"},
    {"id": "video_hook",  "section": "3a. Ad Quality — Video",      "label": "Video Hook",        "desc": "Is the first 3 seconds visually startling to stop the scroll?",                         "type": "visual"},
    {"id": "sound_off",   "section": "3a. Ad Quality — Video",      "label": "Sound-Off Friendly","desc": "Does the video make sense without sound? Are there captions/overlays?",                 "type": "visual"},
    {"id": "pacing",      "section": "3a. Ad Quality — Video",      "label": "Pacing",            "desc": "Editing fast enough? No long pauses. Every ~3 seconds, some movement.",                 "type": "visual"},
    {"id": "text_hook",   "section": "4. Primary Text & Headlines", "label": "Hook",              "desc": "Does the primary text start with a strong hook or question?",                           "type": "copy"},
    {"id": "usps",        "section": "4. Primary Text & Headlines", "label": "USPs",              "desc": "Are USPs clear? Numbers/symbols ($, %, +) used to catch the eye?",                     "type": "copy"},
    {"id": "clarity",     "section": "4. Primary Text & Headlines", "label": "Clarity",           "desc": "Is it written at a 5th-grade reading level?",                                          "type": "copy"},
]

ECOMMERCE_CONTEXT = """For ECOMMERCE: product clarity in under 2 seconds, benefit-led copy, social proof, clear offer/price, strong CTA to product page, product as hero in creative."""
LEADGEN_CONTEXT  = """For LEAD GEN: pain point clarity, lead magnet value crystal clear, low-friction language, trust signals, specific CTA about what happens next, audience self-selection."""


# ─── Brand Storage ────────────────────────────────────────────────────────────

def load_brands():
    if os.path.exists(BRANDS_FILE):
        try:
            with open(BRANDS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_brands(brands: dict):
    with open(BRANDS_FILE, "w") as f:
        json.dump(brands, f, indent=2)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def extract_sheet_id(url):
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return m.group(1) if m else None

def read_public_sheet(url):
    sheet_id = extract_sheet_id(url)
    if not sheet_id:
        return None, "Invalid Google Sheets URL."

    # Check for gid (tab) in URL
    gid_match = re.search(r'[#&?]gid=(\d+)', url)
    gid_param = f"&gid={gid_match.group(1)}" if gid_match else ""

    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid_param}"
    try:
        df = pd.read_csv(csv_url, header=0)
        # Drop rows where ALL cells are empty, but keep rows with at least one value
        df = df.dropna(how="all")
        # Strip column names of extra whitespace
        df.columns = [str(c).strip() for c in df.columns]
        return df, None
    except Exception as e:
        return None, f"Could not read sheet. Make sure sharing is set to 'Anyone with the link can view'. ({e})"

def parse_headlines(raw: str) -> list:
    """Split headlines that are in the same cell separated by newlines or semicolons."""
    if not raw or str(raw).strip() in ("", "nan"):
        return []
    raw = str(raw).strip()
    # split on newlines or semicolons
    lines = re.split(r'\n|;', raw)
    return [l.strip() for l in lines if l.strip()]


def get_canva_screenshot(url: str):
    """Use Microlink API (free, no key needed) to render Canva page and return screenshot."""
    try:
        api = "https://api.microlink.io"
        params = {
            "url": url,
            "screenshot": "true",
            "meta": "false",
            "embed": "screenshot.url",
            "waitForSelector": "canvas,img",  # wait for design to render
            "deviceScaleFactor": "2",
        }
        resp = requests.get(api, params=params, timeout=40)
        if resp.status_code == 200:
            data = resp.json()
            shot = data.get("data", {}).get("screenshot", {})
            shot_url = shot.get("url") if isinstance(shot, dict) else None
            if shot_url:
                img_resp = requests.get(shot_url, timeout=20)
                img_resp.raise_for_status()
                return Image.open(BytesIO(img_resp.content)), None
            return None, "Microlink rendered the page but returned no screenshot URL."
        return None, f"Microlink returned status {resp.status_code}."
    except Exception as e:
        return None, f"Screenshot service error: {e}"


def image_to_base64(img: Image.Image) -> str:
    buf = BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")

def build_checklist_section(audit_mode: str) -> str:
    """Return checklist text filtered by audit mode."""
    types = {"full": ["copy", "visual", "both"], "creative": ["visual", "both"]}
    allowed = types.get(audit_mode, ["copy", "visual", "both"])
    out, section = "", ""
    for item in FULL_CHECKLIST:
        if item["type"] not in allowed:
            continue
        if item["section"] != section:
            section = item["section"]
            out += f"\n### {section}\n"
        out += f'- **{item["id"]}** ({item["label"]}): {item["desc"]}\n'
    return out

def build_system_prompt(account_type, platform, audit_mode, brand: dict = None):
    context = ECOMMERCE_CONTEXT if account_type == "Ecommerce" else LEADGEN_CONTEXT
    brand_section = ""
    if brand:
        brand_section = f"""
**BRAND GUIDELINES — {brand.get('name', 'Unknown')}:**
- Colours: {brand.get('colors', 'Not specified')}
- Fonts: {brand.get('fonts', 'Not specified')}
- Tone of voice: {brand.get('tone', 'Not specified')}
- Brand Dos: {brand.get('dos', 'Not specified')}
- Brand Don'ts: {brand.get('donts', 'Not specified')}
- Additional guidelines: {brand.get('guidelines', 'Not specified')}

Apply these brand guidelines strictly when scoring Brand Alignment and all visual criteria.
"""

    mode_instruction = (
        "You are auditing the CREATIVE ONLY — do not score copy items. "
        "For copy-type items, set score to 0 and rationale to 'N/A — creative-only audit'."
        if audit_mode == "creative"
        else "You are auditing both the ad copy AND the creative."
    )

    return f"""You are a senior paid media creative auditor specialising in {platform} advertising for {account_type} businesses.

{mode_instruction}

{context}
{brand_section}
Scoring: 5=Excellent, 4=Good, 3=Average, 2=Poor, 1=Critical, 0=N/A
Be strict. 4 or 5 must be earned.
For video items (video_hook, sound_off, pacing): if static image, score 0 with rationale "N/A — static image".
Return ONLY valid JSON. No markdown fences. No text outside the JSON."""

def build_user_message(ad_copy: dict, audit_mode: str, canva_url: str, has_image: bool, is_video: bool):
    copy_section = ""
    if audit_mode == "full":
        primary = ad_copy.get("primary_text", "")
        headlines = ad_copy.get("headlines", [])
        descriptions = ad_copy.get("descriptions", [])
        final_url = ad_copy.get("final_url", "")

        copy_section = "\n**AD COPY:**\n"
        if primary:
            copy_section += f"Primary Text:\n{primary}\n\n"
        if headlines:
            copy_section += "Headlines:\n" + "\n".join(f"  - {h}" for h in headlines) + "\n\n"
        if descriptions:
            copy_section += "Descriptions:\n" + "\n".join(f"  - {d}" for d in descriptions) + "\n\n"
        if final_url:
            copy_section += f"Final URL: {final_url}\n"

    creative_note = ""
    if has_image and not is_video:
        creative_note = "[Static image creative attached — analyse visually for all creative criteria.]"
    elif is_video:
        creative_note = "[Video creative uploaded — this is a video ad. Score video-specific items (video_hook, sound_off, pacing). A thumbnail/frame is attached if provided.]"
    else:
        creative_note = f"[Canva link: {canva_url} — no image could be fetched. Score visual items based on best judgement from copy context.]"

    ids_filtered = [item["id"] for item in FULL_CHECKLIST]
    empty = ",\n    ".join(f'"{i}": {{"score": 0, "rationale": "..."}}' for i in ids_filtered)

    return f"""Please audit this ad creative:
{copy_section}
**CREATIVE:**
{creative_note}

**CHECKLIST:**
{build_checklist_section(audit_mode)}

Return ONLY this JSON:

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

def run_audit(api_key, account_type, platform, audit_mode, ad_copy, image, canva_url, is_video, brand=None):
    client = anthropic.Anthropic(api_key=api_key)
    has_image = image is not None
    system = build_system_prompt(account_type, platform, audit_mode, brand)
    user_text = build_user_message(ad_copy, audit_mode, canva_url, has_image, is_video)

    content = []
    if has_image:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_to_base64(image)}
        })
    content.append({"type": "text", "text": user_text})

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": content}]
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    return json.loads(raw)


# ─── Render Scorecard ─────────────────────────────────────────────────────────

def render_scorecard(results, account_type, platform, audit_mode):
    scores   = results.get("scores", {})
    overall  = int(results.get("overall_score", 0))
    fixes    = [f for f in results.get("priority_fixes", []) if f and f != "..."]
    strengths= [s for s in results.get("strengths", []) if s and s != "..."]
    ready    = results.get("ready_to_publish", False)
    verdict  = results.get("one_line_verdict", "")

    oc = SCORE_COLOR.get(overall, "#94a3b8")
    rc = "#22c55e" if ready else "#ef4444"
    rt = "✅ Ready to Publish" if ready else "🚫 Not Ready to Publish"

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"""
        <div style="border:3px solid {oc}; border-radius:14px; padding:28px;
                    text-align:center; background:{oc}12">
          <div style="font-size:3.8em; font-weight:900; color:{oc}; line-height:1">{overall}/5</div>
          <div style="font-size:.95em; color:#64748b; margin:6px 0">Overall Score</div>
          <div style="font-weight:700; color:{rc}; font-size:1em">{rt}</div>
          <div style="color:#64748b; font-size:.85em; margin-top:10px; font-style:italic">"{verdict}"</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    allowed_types = ["copy", "visual", "both"] if audit_mode == "full" else ["visual", "both"]
    current_section = ""
    for item in FULL_CHECKLIST:
        if item["type"] not in allowed_types:
            continue
        if item["section"] != current_section:
            current_section = item["section"]
            st.markdown(f'<div class="section-header">{current_section}</div>', unsafe_allow_html=True)

        sd    = scores.get(item["id"], {})
        score = sd.get("score", 0)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 0
        rationale = sd.get("rationale", "—")
        c   = SCORE_COLOR.get(score, "#94a3b8")
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
              <div style="font-size:.6em; color:{c}; font-weight:700;
                          text-transform:uppercase; letter-spacing:.5px">{lbl}</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<div style='padding-top:8px; color:#334155; line-height:1.5'>{rationale}</div>",
                        unsafe_allow_html=True)
        st.markdown("")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🔴 Priority Fixes")
        for f in fixes:
            st.markdown(f'<div class="fix-item">{f}</div>', unsafe_allow_html=True)
    with col2:
        st.markdown("### 🟢 Strengths")
        for s in strengths:
            st.markdown(f'<div class="strength-item">{s}</div>', unsafe_allow_html=True)


def generate_html_report(results, account_type, platform, audit_mode, ad_copy, canva_url, brand_name=""):
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

    allowed_types = ["copy", "visual", "both"] if audit_mode == "full" else ["visual", "both"]
    rows = ""
    for item in FULL_CHECKLIST:
        if item["type"] not in allowed_types:
            continue
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

    headlines_html = "".join(
        f"<li>{h}</li>" for h in ad_copy.get("headlines", [])
    )
    fix_items      = "".join(f"<li style='margin:6px 0'>{f}</li>" for f in fixes)
    strength_items = "".join(f"<li style='margin:6px 0'>{s}</li>" for s in strengths)
    mode_label     = "Full Audit" if audit_mode == "full" else "Creative-Only Audit"
    brand_label    = f" &nbsp;|&nbsp; Brand: {brand_name}" if brand_name else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Ad Creative Audit Report</title>
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
  @media print{{body{{background:white}}.container{{box-shadow:none}}}}
</style></head>
<body><div class="container">
  <h1>📋 Ad Creative Audit Report</h1>
  <div class="meta">Generated: {now} &nbsp;|&nbsp; {platform} &nbsp;|&nbsp; {account_type} &nbsp;|&nbsp; {mode_label}{brand_label}</div>

  <div style="border:3px solid {oc};border-radius:14px;padding:24px;text-align:center;
              background:{oc}10;display:inline-block;min-width:220px">
    <div style="font-size:3em;font-weight:900;color:{oc};line-height:1">{overall}/5</div>
    <div style="color:#64748b;margin:4px 0">Overall Score</div>
    <div style="color:{rc};font-weight:700;margin-top:8px">{rt}</div>
    <div style="font-style:italic;color:#475569;margin-top:8px">&ldquo;{verdict}&rdquo;</div>
  </div>

  <h2>Ad Copy</h2>
  <table><tbody>
    <tr><td style="padding:8px 10px;font-weight:600;color:#374151;border-bottom:1px solid #f1f5f9;width:160px">Primary Text</td>
        <td style="padding:8px 10px;border-bottom:1px solid #f1f5f9;white-space:pre-wrap">{ad_copy.get('primary_text','—')}</td></tr>
    <tr><td style="padding:8px 10px;font-weight:600;color:#374151;border-bottom:1px solid #f1f5f9">Headlines</td>
        <td style="padding:8px 10px;border-bottom:1px solid #f1f5f9"><ul style="margin:0;padding-left:18px">{headlines_html}</ul></td></tr>
    <tr><td style="padding:8px 10px;font-weight:600;color:#374151;border-bottom:1px solid #f1f5f9">Descriptions</td>
        <td style="padding:8px 10px;border-bottom:1px solid #f1f5f9">{' / '.join(ad_copy.get('descriptions',[]))}</td></tr>
    <tr><td style="padding:8px 10px;font-weight:600;color:#374151">Final URL</td>
        <td style="padding:8px 10px">{ad_copy.get('final_url','—')}</td></tr>
  </tbody></table>

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


# ─── Pages ────────────────────────────────────────────────────────────────────

def page_audit(api_key):
    st.title("📋 Ad Creative Audit Agent")
    st.caption("Automated creative auditing powered by Claude AI")

    brands = load_brands()

    # ── Sidebar controls ──────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ Audit Settings")
        platform     = st.selectbox("Ad Platform", ["Meta Ads", "Google Ads"])
        account_type = st.selectbox("Account Type", ["Ecommerce", "Lead Gen"])
        audit_mode   = st.radio("Audit Mode", ["Full Audit", "Creative Only"],
                                help="Full Audit scores copy + creative. Creative Only scores the image/video only.")
        audit_mode_key = "full" if audit_mode == "Full Audit" else "creative"

        st.markdown("---")
        st.markdown("**Brand / Client**")
        brand_options = ["None (no brand guidelines)"] + list(brands.keys())
        selected_brand_name = st.selectbox("Apply brand guidelines", brand_options)
        selected_brand = brands.get(selected_brand_name) if selected_brand_name != "None (no brand guidelines)" else None
        if selected_brand:
            st.caption(f"✅ Brand DNA loaded: **{selected_brand_name}**")

        st.markdown("---")
        st.caption("Matriarch Digital — Ad Creative Audit Agent")

    st.markdown("---")

    # ── Step 1: Google Sheet ──────────────────────────────────────────────────
    # ad_copy is set by either the sheet flow or left empty for creative-only
    ad_copy = {"primary_text": "", "headlines": [], "descriptions": [], "final_url": ""}

    if audit_mode_key == "full":
        st.markdown("### 📊 Step 1 — Ad Copy (Google Sheet)")
        sheet_url = st.text_input("Google Sheet URL (must be public — paste the tab link you want to scan)",
                                  placeholder="https://docs.google.com/spreadsheets/d/...")

        df = None

        if sheet_url:
            with st.spinner("Reading sheet..."):
                df, err = read_public_sheet(sheet_url)
            if err:
                st.error(f"❌ {err}")
            elif df is not None:

                # ── Column auto-detection ─────────────────────────────────
                def _find_col(df_cols, keywords):
                    for col in df_cols:
                        cl = col.lower()
                        if any(kw in cl for kw in keywords):
                            return col
                    return None

                real_cols = list(df.columns)
                auto_pt   = _find_col(real_cols, ["primary text", "primary", "ad copy", "body"])
                auto_hl   = _find_col(real_cols, ["headline", "heading", "title"])
                auto_desc = _find_col(real_cols, ["description", "desc"])
                auto_url  = _find_col(real_cols, ["url", "link", "destination"])

                NONE_OPT = "— not in sheet —"
                cols_opts = [NONE_OPT] + real_cols

                def _idx(auto):
                    return cols_opts.index(auto) if auto and auto in cols_opts else 0

                with st.expander("⚙️ Column mapping (auto-detected — expand to adjust)", expanded=False):
                    cm1, cm2, cm3, cm4 = st.columns(4)
                    with cm1:
                        pt_col   = st.selectbox("Primary Text",  cols_opts, index=_idx(auto_pt),  key="pt_col")
                    with cm2:
                        hl_col   = st.selectbox("Headlines",     cols_opts, index=_idx(auto_hl),  key="hl_col")
                    with cm3:
                        desc_col = st.selectbox("Descriptions",  cols_opts, index=_idx(auto_desc),key="desc_col")
                    with cm4:
                        url_col  = st.selectbox("Final URL",     cols_opts, index=_idx(auto_url), key="url_col")

                # ── Parse all rows into ad_copy dicts ─────────────────────
                def _parse_row(row):
                    pt  = str(row[pt_col])   if pt_col   != NONE_OPT else ""
                    hl  = str(row[hl_col])   if hl_col   != NONE_OPT else ""
                    dc  = str(row[desc_col]) if desc_col != NONE_OPT else ""
                    url = str(row[url_col])  if url_col  != NONE_OPT else ""
                    return {
                        "primary_text": pt  if pt  not in ("", "nan") else "",
                        "headlines":    parse_headlines(hl),
                        "descriptions": parse_headlines(dc),
                        "final_url":    url if url not in ("", "nan") else "",
                    }

                all_ads = [_parse_row(df.iloc[i]) for i in range(len(df))]

                st.markdown(f"**{len(all_ads)} ad(s) found — select one to audit:**")
                st.markdown("<br>", unsafe_allow_html=True)

                for i, ac in enumerate(all_ads):
                    # Build a one-line label from first non-empty field
                    preview_label = (
                        ac["primary_text"][:60]
                        or (ac["headlines"][0][:60] if ac["headlines"] else "")
                        or f"Row {i+1}"
                    )
                    with st.expander(f"📄 Ad {i+1} — {preview_label}{'…' if len(preview_label)==60 else ''}", expanded=(i==0)):
                        st.markdown('<div class="copy-preview">', unsafe_allow_html=True)
                        if ac["primary_text"]:
                            st.markdown('<div class="copy-label">Primary Text</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="copy-value">{ac["primary_text"]}</div>', unsafe_allow_html=True)
                        if ac["headlines"]:
                            st.markdown('<div class="copy-label" style="margin-top:12px">Headlines</div>', unsafe_allow_html=True)
                            for h in ac["headlines"]:
                                st.markdown(f'<div class="headline-item">📌 {h}</div>', unsafe_allow_html=True)
                        if ac["descriptions"]:
                            st.markdown('<div class="copy-label" style="margin-top:12px">Descriptions</div>', unsafe_allow_html=True)
                            for d in ac["descriptions"]:
                                st.markdown(f'<div class="headline-item">📝 {d}</div>', unsafe_allow_html=True)
                        if ac["final_url"]:
                            st.markdown(f'<div class="copy-label" style="margin-top:12px">Final URL</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="copy-value">🔗 {ac["final_url"]}</div>', unsafe_allow_html=True)
                        st.markdown('</div>', unsafe_allow_html=True)

                        if st.button(f"⚡ Select Ad {i+1} for Audit", key=f"sel_{i}", use_container_width=True):
                            st.session_state["selected_ad_copy"] = ac
                            st.rerun()

                # Use session-state selected ad, or default to first row
                if "selected_ad_copy" in st.session_state:
                    ad_copy = st.session_state["selected_ad_copy"]
                    st.success(f"✅ Ad selected — ready to audit below.")
                elif all_ads:
                    ad_copy = all_ads[0]
    else:
        st.info("ℹ️ Creative-Only mode — no ad copy needed.")

    st.markdown("---")

    # ── Step 2: Creative ──────────────────────────────────────────────────────
    st.markdown("### 🎨 Step 2 — Creative")

    canva_url = st.text_input("Canva Share Link (paste link → auto-screenshot)",
                              placeholder="https://www.canva.com/design/...")

    creative_image = None
    is_video       = False

    # Auto-screenshot from Canva link via Microlink
    if canva_url:
        # Only re-fetch if the URL changed
        if st.session_state.get("canva_fetched_url") != canva_url:
            with st.spinner("📸 Capturing Canva screenshot (10–30 sec)..."):
                img, err = get_canva_screenshot(canva_url)
            if img:
                st.session_state["canva_img"] = img
                st.session_state["canva_fetched_url"] = canva_url
                st.success("✅ Canva creative captured automatically!")
            else:
                st.session_state["canva_img"] = None
                st.session_state["canva_fetched_url"] = canva_url
                st.warning(f"⚠️ Auto-capture failed ({err}) — upload manually below.")

        if st.session_state.get("canva_img"):
            creative_image = st.session_state["canva_img"]

    st.markdown("**Or upload manually** (use if Canva auto-capture fails):")
    tab_img, tab_vid = st.tabs(["🖼️ Static Image", "🎬 Video"])

    with tab_img:
        uploaded_img = st.file_uploader("Upload image (PNG, JPG, WebP)", type=["png", "jpg", "jpeg", "webp"],
                                        key="img_upload", label_visibility="collapsed")
        if uploaded_img:
            creative_image = Image.open(uploaded_img)
            is_video = False
            st.success("✅ Image uploaded")

    with tab_vid:
        st.caption("Upload a screenshot or thumbnail of the first frame/hook of your video — Claude will score all video-specific criteria.")
        uploaded_vid = st.file_uploader("Upload video thumbnail (PNG or JPG)", type=["png", "jpg", "jpeg"],
                                        key="vid_upload",
                                        label_visibility="collapsed")
        if uploaded_vid:
            creative_image = Image.open(uploaded_vid)
            is_video = True
            st.success("✅ Video thumbnail uploaded — video audit mode active")

    if creative_image:
        st.image(creative_image, caption="Creative Preview", use_container_width=True)

    st.markdown("---")

    # ── Run Audit ─────────────────────────────────────────────────────────────
    can_audit = bool(creative_image or canva_url)
    if not can_audit:
        st.info("Paste a Canva link or upload a creative to run the audit.")

    if can_audit:
        if st.button("⚡ Run Audit", type="primary", use_container_width=True):
            with st.spinner("Claude is auditing your creative — 15–30 seconds..."):
                try:
                    results = run_audit(
                        api_key, account_type, platform, audit_mode_key,
                        ad_copy, creative_image, canva_url or "", is_video, selected_brand
                    )
                    st.session_state["results"]       = results
                    st.session_state["ad_copy"]       = ad_copy
                    st.session_state["account_type"]  = account_type
                    st.session_state["platform"]      = platform
                    st.session_state["audit_mode"]    = audit_mode_key
                    st.session_state["canva_url"]     = canva_url or ""
                    st.session_state["brand_name"]    = selected_brand_name if selected_brand else ""
                    st.success("✅ Audit complete!")
                except anthropic.AuthenticationError:
                    st.error("❌ Invalid API key. Check Streamlit secrets → ANTHROPIC_API_KEY")
                except json.JSONDecodeError as e:
                    st.error(f"❌ Unexpected response format. Try again. ({e})")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── Results ───────────────────────────────────────────────────────────────
    if "results" in st.session_state:
        st.markdown("---")
        st.markdown("## Audit Results")
        render_scorecard(
            st.session_state["results"],
            st.session_state.get("account_type", ""),
            st.session_state.get("platform", ""),
            st.session_state.get("audit_mode", "full"),
        )
        st.markdown("---")
        html = generate_html_report(
            st.session_state["results"],
            st.session_state.get("account_type", ""),
            st.session_state.get("platform", ""),
            st.session_state.get("audit_mode", "full"),
            st.session_state.get("ad_copy", {}),
            st.session_state.get("canva_url", ""),
            st.session_state.get("brand_name", ""),
        )
        st.download_button(
            "⬇️ Download HTML Report",
            data=html,
            file_name=f"audit_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
            mime="text/html",
            type="primary",
            use_container_width=True
        )
        st.caption("Open in browser → File → Print → Save as PDF")


def page_brand_dna():
    st.title("🎨 Brand DNA Manager")
    st.caption("Create and manage brand profiles. These are applied to audits to check brand alignment.")

    brands = load_brands()

    col1, col2 = st.columns([1, 2])

    with col1:
        st.markdown("### Saved Brands")
        if not brands:
            st.info("No brands saved yet.")
        else:
            for name in list(brands.keys()):
                bcol1, bcol2 = st.columns([3, 1])
                with bcol1:
                    st.markdown(f"**{name}**")
                with bcol2:
                    if st.button("🗑️", key=f"del_{name}", help=f"Delete {name}"):
                        del brands[name]
                        save_brands(brands)
                        st.rerun()

        st.markdown("---")
        # Export
        if brands:
            st.download_button(
                "⬇️ Export brands.json",
                data=json.dumps(brands, indent=2),
                file_name="brands.json",
                mime="application/json",
                use_container_width=True
            )

        # Import
        st.markdown("**Import brands.json:**")
        imported = st.file_uploader("Import", type=["json"], label_visibility="collapsed")
        if imported:
            try:
                imported_brands = json.load(imported)
                brands.update(imported_brands)
                save_brands(brands)
                st.success(f"✅ Imported {len(imported_brands)} brand(s)")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Import failed: {e}")

    with col2:
        st.markdown("### Add / Edit Brand")

        edit_options = ["— Create new brand —"] + list(brands.keys())
        edit_target  = st.selectbox("Edit existing or create new", edit_options)

        existing = brands.get(edit_target, {}) if edit_target != "— Create new brand —" else {}

        with st.form("brand_form"):
            name = st.text_input("Brand / Client Name *", value=existing.get("name", ""))
            st.markdown("---")

            col_a, col_b = st.columns(2)
            with col_a:
                colors = st.text_area("Brand Colours",
                                      value=existing.get("colors", ""),
                                      placeholder="e.g. Primary: #FF6B35, Secondary: #FFFFFF, Accent: #1A1A2E",
                                      height=80)
                fonts  = st.text_area("Fonts / Typography",
                                      value=existing.get("fonts", ""),
                                      placeholder="e.g. Headings: Montserrat Bold, Body: Open Sans Regular",
                                      height=80)
                tone   = st.text_area("Tone of Voice",
                                      value=existing.get("tone", ""),
                                      placeholder="e.g. Confident, conversational, no jargon, aspirational",
                                      height=80)
            with col_b:
                dos    = st.text_area("Brand Dos ✅",
                                      value=existing.get("dos", ""),
                                      placeholder="e.g. Use lifestyle imagery, always show product in use, use white backgrounds",
                                      height=80)
                donts  = st.text_area("Brand Don'ts 🚫",
                                      value=existing.get("donts", ""),
                                      placeholder="e.g. No dark backgrounds, no stock photos, never use Comic Sans",
                                      height=80)

            guidelines = st.text_area(
                "Additional Guidelines / Brand Notes",
                value=existing.get("guidelines", ""),
                placeholder="Paste brand brief, style guide notes, client requirements...",
                height=120
            )

            # File upload for brand guidelines doc
            uploaded_guide = st.file_uploader(
                "Upload brand guidelines (PDF or TXT — text will be extracted)",
                type=["txt", "pdf"],
                help="Text files only for now. PDF text extraction requires additional setup."
            )
            if uploaded_guide:
                if uploaded_guide.type == "text/plain":
                    file_text = uploaded_guide.read().decode("utf-8", errors="ignore")
                    guidelines = (guidelines + "\n\n" + file_text).strip()
                    st.success(f"✅ Text extracted from {uploaded_guide.name}")
                else:
                    st.info("ℹ️ PDF upload noted — paste the key guidelines as text above for best results.")

            submitted = st.form_submit_button("💾 Save Brand", type="primary", use_container_width=True)
            if submitted:
                if not name.strip():
                    st.error("Brand name is required.")
                else:
                    brands[name.strip()] = {
                        "name":       name.strip(),
                        "colors":     colors,
                        "fonts":      fonts,
                        "tone":       tone,
                        "dos":        dos,
                        "donts":      donts,
                        "guidelines": guidelines,
                    }
                    save_brands(brands)
                    st.success(f"✅ Brand **{name}** saved!")
                    st.rerun()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Load API key from secrets
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        st.error("❌ ANTHROPIC_API_KEY not found in Streamlit secrets.")
        st.stop()

    with st.sidebar:
        st.markdown("# 📋 Ad Audit Agent")
        page = st.radio("", ["🔍 Run Audit", "🎨 Brand DNA"], label_visibility="collapsed")
        st.markdown("---")

    if page == "🔍 Run Audit":
        page_audit(api_key)
    else:
        page_brand_dna()


if __name__ == "__main__":
    main()
