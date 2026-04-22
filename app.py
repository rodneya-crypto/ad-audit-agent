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
from streamlit_paste_button import paste_image_button as pbutton

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
        resp = requests.get(
            "https://api.microlink.io",
            params={"url": url, "screenshot": "true", "meta": "false"},
            headers={"Accept": "application/json"},
            timeout=45,
        )
        if not resp.content:
            return None, "Screenshot service returned an empty response."
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            return None, f"Unexpected response from screenshot service (HTTP {resp.status_code})."
        data = resp.json()
        if data.get("status") != "success":
            return None, f"Screenshot service: {data.get('message', 'unknown error')}."
        shot = data.get("data", {}).get("screenshot", {})
        shot_url = shot.get("url") if isinstance(shot, dict) else None
        if not shot_url:
            return None, "No screenshot URL returned."
        img_resp = requests.get(shot_url, timeout=20)
        img_resp.raise_for_status()
        return Image.open(BytesIO(img_resp.content)), None
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

def build_user_message(ad_copy: dict, audit_mode: str, canva_url: str, num_images: int, is_video: bool):
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
    if num_images > 0 and not is_video:
        if num_images > 1:
            creative_note = f"[{num_images} static image creatives attached — analyse each visually for all creative criteria.]"
        else:
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

def run_audit(api_key, account_type, platform, audit_mode, ad_copy, images, canva_url, is_video, brand=None):
    client = anthropic.Anthropic(api_key=api_key)
    images = images or []
    system = build_system_prompt(account_type, platform, audit_mode, brand)
    user_text = build_user_message(ad_copy, audit_mode, canva_url, len(images), is_video)

    content = []
    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_to_base64(img)}
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

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ Settings")
        platform     = st.selectbox("Platform", ["Meta Ads", "Google Ads"])
        account_type = st.selectbox("Account Type", ["Ecommerce", "Lead Gen"])
        audit_mode   = st.radio(
            "Audit Mode", ["Full Audit", "Creative Only"],
            help="Full Audit scores copy + creative. Creative Only scores the image/video only."
        )
        audit_mode_key = "full" if audit_mode == "Full Audit" else "creative"

        st.markdown("---")
        brand_options = ["None (no brand guidelines)"] + list(brands.keys())
        selected_brand_name = st.selectbox("Brand / Client", brand_options)
        selected_brand = brands.get(selected_brand_name) if selected_brand_name != "None (no brand guidelines)" else None
        if selected_brand:
            st.caption(f"✅ **{selected_brand_name}** loaded")

        st.markdown("---")
        st.caption("Matriarch Digital — Ad Creative Audit Agent")

    st.markdown("---")

    # ─── Step 1: Ad Copy ──────────────────────────────────────────────────────
    selected_ads = []
    canva_url    = ""

    if audit_mode_key == "full":
        st.markdown("### 📊 Step 1 — Ad Copy")
        sheet_url = st.text_input(
            "Google Sheet URL",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            help="Sheet must be shared as 'Anyone with the link can view'. Paste the specific tab link."
        )

        if sheet_url:
            with st.spinner("Loading sheet..."):
                df, err = read_public_sheet(sheet_url)
            if err:
                st.error(f"❌ {err}")
            elif df is not None:

                # Truncate at sentinel row
                _sentinel_kws = ["meta ads copy", "creative checklist"]
                _cutoff = len(df)
                for _ri in range(len(df)):
                    _row_text = " ".join(str(v).lower() for v in df.iloc[_ri].values)
                    if all(kw in _row_text for kw in _sentinel_kws):
                        _cutoff = _ri
                        break
                if _cutoff < len(df):
                    df = df.iloc[:_cutoff].reset_index(drop=True)

                # Column helpers
                def _find_col(df_cols, keywords):
                    for col in df_cols:
                        if any(kw in col.lower() for kw in keywords):
                            return col
                    return None

                def _find_merged_siblings(df_cols, anchor_col):
                    if anchor_col is None:
                        return []
                    try:
                        idx = df_cols.index(anchor_col)
                    except ValueError:
                        return []
                    siblings = []
                    for c in df_cols[idx + 1:]:
                        if re.match(r'^Unnamed: \d+$', c):
                            siblings.append(c)
                        else:
                            break
                    return siblings

                real_cols = list(df.columns)
                auto_pt   = _find_col(real_cols, ["primary text", "primary", "ad copy", "body"])
                auto_hl   = _find_col(real_cols, ["headline", "heading", "title"])
                auto_desc = _find_col(real_cols, ["description", "desc"])
                auto_url  = _find_col(real_cols, ["url", "link", "destination"])

                pt_siblings = _find_merged_siblings(real_cols, auto_pt)
                _pt_default = [c for c in ([auto_pt] + pt_siblings) if c in real_cols]

                NONE_OPT  = "— not in sheet —"
                cols_opts = [NONE_OPT] + real_cols

                def _idx(auto):
                    return cols_opts.index(auto) if auto and auto in cols_opts else 0

                with st.expander("⚙️ Column mapping (auto-detected — expand to adjust)", expanded=False):
                    pt_cols = st.multiselect(
                        "Primary Text column(s)",
                        real_cols,
                        default=_pt_default,
                        key="pt_cols",
                        help="Select every column that contains ad copy. Merged-header siblings are auto-added."
                    )
                    if pt_siblings:
                        st.caption("Merged header detected — sibling columns auto-included above.")
                    _c2, _c3, _c4 = st.columns(3)
                    with _c2:
                        hl_col   = st.selectbox("Headlines",    cols_opts, index=_idx(auto_hl),   key="hl_col")
                    with _c3:
                        desc_col = st.selectbox("Descriptions", cols_opts, index=_idx(auto_desc), key="desc_col")
                    with _c4:
                        url_col  = st.selectbox("Final URL",    cols_opts, index=_idx(auto_url),  key="url_col")

                def _parse_row(row):
                    if pt_cols:
                        pt_parts = [str(row[c]) for c in pt_cols if str(row[c]) not in ("", "nan", "NaN")]
                        pt = "\n".join(pt_parts)
                    else:
                        pt = ""
                    hl  = str(row[hl_col])   if hl_col   != NONE_OPT else ""
                    dc  = str(row[desc_col]) if desc_col != NONE_OPT else ""
                    url = str(row[url_col])  if url_col  != NONE_OPT else ""
                    return {
                        "primary_text": pt,
                        "headlines":    parse_headlines(hl),
                        "descriptions": parse_headlines(dc),
                        "final_url":    url if url not in ("", "nan", "NaN") else "",
                    }

                def _has_content(ac):
                    return bool(ac["primary_text"] or ac["headlines"] or ac["descriptions"] or ac["final_url"])

                _checklist_strings = set()
                for _ci in FULL_CHECKLIST:
                    _checklist_strings.update({
                        _ci["section"].lower().strip(), _ci["label"].lower().strip(),
                        _ci["id"].lower().strip(),      _ci["desc"].lower().strip(),
                    })

                def _is_checklist_row(ac):
                    pt = ac["primary_text"].strip()
                    if not pt:
                        return False
                    if pt.lower() in _checklist_strings:
                        return True
                    if re.match(r'^\d+[a-z]?\.\s+', pt):
                        return True
                    if len(pt) < 30 and not ac["headlines"] and not ac["descriptions"] and not ac["final_url"]:
                        return True
                    return False

                all_ads = [_parse_row(df.iloc[i]) for i in range(len(df))]
                all_ads = [ac for ac in all_ads if _has_content(ac) and not _is_checklist_row(ac)]

                if not all_ads:
                    st.warning("No ad rows found. Check column mapping above.")
                else:
                    st.markdown(f"**{len(all_ads)} ad row(s) found** — check the box next to each one you want to audit:")

                    # ── Full-preview data table with Select checkboxes ────
                    _rows = []
                    for i, ac in enumerate(all_ads):
                        hl_str = " | ".join(ac["headlines"][:3])
                        if len(ac["headlines"]) > 3:
                            hl_str += f" +{len(ac['headlines'])-3} more"
                        _rows.append({
                            "Select":       False,
                            "#":            i + 1,
                            "Primary Text": ac["primary_text"],
                            "Headlines":    hl_str,
                            "Descriptions": " | ".join(ac["descriptions"][:2]),
                            "URL":          ac["final_url"],
                        })
                    _display_df = pd.DataFrame(_rows)

                    _edited = st.data_editor(
                        _display_df,
                        column_config={
                            "Select":       st.column_config.CheckboxColumn("✓", width="small"),
                            "#":            st.column_config.NumberColumn("#", width="small"),
                            "Primary Text": st.column_config.TextColumn("Primary Text", width="large"),
                            "Headlines":    st.column_config.TextColumn("Headlines",    width="medium"),
                            "Descriptions": st.column_config.TextColumn("Descriptions", width="medium"),
                            "URL":          st.column_config.TextColumn("URL",          width="small"),
                        },
                        disabled=["#", "Primary Text", "Headlines", "Descriptions", "URL"],
                        hide_index=True,
                        use_container_width=True,
                        height=min(500, 45 * len(all_ads) + 55),
                        key="ad_selector_editor",
                    )

                    selected_ads = [all_ads[i] for i, row in _edited.iterrows() if row["Select"]]
                    if selected_ads:
                        st.success(f"✅ {len(selected_ads)} ad(s) selected for audit")

        st.session_state["selected_ads"] = selected_ads

    else:
        st.info("ℹ️ Creative Only mode — no ad copy needed. Add your creative below.")

    st.markdown("---")

    # ─── Step 2: Creative ─────────────────────────────────────────────────────
    st.markdown("### 🎨 Step 2 — Creative")

    if "pasted_images" not in st.session_state:
        st.session_state["pasted_images"] = []
    if "pasted_image_hashes" not in st.session_state:
        st.session_state["pasted_image_hashes"] = []

    is_video        = False
    uploaded_images = []
    video_thumbnail = None

    left_col, right_col = st.columns(2)

    with left_col:
        # ── Canva link ────────────────────────────────────────────────────
        st.markdown("**Option A — Canva Link** *(auto-screenshot)*")
        canva_url = st.text_input(
            "canva_link",
            placeholder="https://www.canva.com/design/...",
            label_visibility="collapsed",
        )
        if canva_url:
            if st.session_state.get("canva_fetched_url") != canva_url:
                with st.spinner("Capturing Canva screenshot (10–30 sec)..."):
                    img, err = get_canva_screenshot(canva_url)
                if img:
                    st.session_state["canva_img"] = img
                    st.session_state["canva_fetched_url"] = canva_url
                    st.success("✅ Canva screenshot captured!")
                else:
                    st.session_state["canva_img"] = None
                    st.session_state["canva_fetched_url"] = canva_url
                    st.warning(f"⚠️ Auto-capture failed — upload manually. ({err})")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Clipboard paste (outside any tab so it stays mounted) ─────────
        st.markdown("**Option B — Paste from Clipboard**")
        st.caption("① Copy an image (Ctrl+C / Cmd+C)  →  ② Click the button below  →  ③ Paste (Ctrl+V / Cmd+V)")
        paste_result = pbutton(
            label="📋 Paste Image",
            text_color="#ffffff",
            background_color="#1e293b",
            hover_background_color="#334155",
            key="paste_btn",
        )
        if paste_result.image_data is not None:
            import hashlib as _hl
            _buf = BytesIO()
            paste_result.image_data.save(_buf, format="PNG")
            _hash = _hl.md5(_buf.getvalue()).hexdigest()
            if _hash not in st.session_state["pasted_image_hashes"]:
                st.session_state["pasted_image_hashes"].append(_hash)
                st.session_state["pasted_images"].append(paste_result.image_data)
                st.success(f"✅ Image added — {len(st.session_state['pasted_images'])} pasted so far")
        if st.session_state["pasted_images"]:
            _np = len(st.session_state["pasted_images"])
            st.caption(f"{_np} pasted image{'s' if _np > 1 else ''} in collection")
            if st.button("🗑️ Clear pasted images", key="clear_pasted"):
                st.session_state["pasted_images"] = []
                st.session_state["pasted_image_hashes"] = []
                st.rerun()

    with right_col:
        # ── File upload ───────────────────────────────────────────────────
        st.markdown("**Option C — Upload Image(s)**")
        uploaded_files = st.file_uploader(
            "upload_images",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="img_upload",
        )
        if uploaded_files:
            uploaded_images = [Image.open(f) for f in uploaded_files]
            st.success(f"✅ {len(uploaded_images)} image(s) ready")

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Video thumbnail ───────────────────────────────────────────────
        st.markdown("**Option D — Video Thumbnail** *(for video ads)*")
        st.caption("Upload a screenshot of the first frame — Claude scores all video criteria.")
        uploaded_vid = st.file_uploader(
            "video_thumb",
            type=["png", "jpg", "jpeg"],
            key="vid_upload",
            label_visibility="collapsed",
        )
        if uploaded_vid:
            video_thumbnail = Image.open(uploaded_vid)
            is_video = True
            st.success("✅ Video thumbnail loaded")

    # Combine all image sources
    all_creative_images = []
    if st.session_state.get("canva_img"):
        all_creative_images.append(st.session_state["canva_img"])
    all_creative_images.extend(st.session_state.get("pasted_images", []))
    all_creative_images.extend(uploaded_images)
    if video_thumbnail:
        all_creative_images.append(video_thumbnail)

    if all_creative_images:
        st.markdown("**Creative Preview**")
        n_prev = min(len(all_creative_images), 4)
        prev_cols = st.columns(n_prev)
        for i, img in enumerate(all_creative_images):
            with prev_cols[i % n_prev]:
                st.image(img, caption=f"Image {i + 1}", width=180)

    st.markdown("---")

    # ─── Run Audit ────────────────────────────────────────────────────────────
    ads_to_audit = st.session_state.get("selected_ads", [])
    if audit_mode_key == "creative":
        ads_to_audit = [{"primary_text": "", "headlines": [], "descriptions": [], "final_url": ""}]

    can_audit = bool(all_creative_images or canva_url)
    if not can_audit:
        st.info("Add a Canva link or upload a creative in Step 2 to enable the audit.")
    elif audit_mode_key == "full" and not ads_to_audit:
        st.info("Select at least one ad row in Step 1 to run the audit.")

    if can_audit and (audit_mode_key == "creative" or ads_to_audit):
        n = len(ads_to_audit)
        btn_label = f"⚡ Run Audit — {n} Ad{'s' if n > 1 else ''}" if n > 1 else "⚡ Run Audit"
        if st.button(btn_label, type="primary", use_container_width=True):
            all_results = []
            progress = st.progress(0, text="Starting audit...")
            for idx, ac in enumerate(ads_to_audit):
                progress.progress(idx / n, text=f"Auditing ad {idx + 1} of {n}...")
                try:
                    res = run_audit(
                        api_key, account_type, platform, audit_mode_key,
                        ac, all_creative_images, canva_url or "", is_video, selected_brand
                    )
                    all_results.append({"ad_copy": ac, "results": res})
                except anthropic.AuthenticationError:
                    st.error("❌ Invalid API key — check Streamlit secrets → ANTHROPIC_API_KEY")
                    break
                except json.JSONDecodeError as e:
                    st.error(f"❌ Ad {idx + 1}: Unexpected response format. ({e})")
                except Exception as e:
                    st.error(f"❌ Ad {idx + 1}: {e}")
            progress.progress(1.0, text="Done!")
            if all_results:
                st.session_state["all_results"]  = all_results
                st.session_state["account_type"] = account_type
                st.session_state["platform"]     = platform
                st.session_state["audit_mode"]   = audit_mode_key
                st.session_state["canva_url"]    = canva_url or ""
                st.session_state["brand_name"]   = selected_brand_name if selected_brand else ""
                st.success(f"✅ Audit complete — {len(all_results)} ad(s) scored!")

    # ─── Results ──────────────────────────────────────────────────────────────
    if "all_results" in st.session_state:
        all_results    = st.session_state["all_results"]
        account_type_r = st.session_state.get("account_type", "")
        platform_r     = st.session_state.get("platform", "")
        audit_mode_r   = st.session_state.get("audit_mode", "full")
        canva_url_r    = st.session_state.get("canva_url", "")
        brand_name_r   = st.session_state.get("brand_name", "")

        st.markdown("---")
        st.markdown(f"## Audit Results — {len(all_results)} Ad(s)")

        for idx, entry in enumerate(all_results):
            ac    = entry["ad_copy"]
            res   = entry["results"]
            label = (
                ac.get("primary_text", "")[:50]
                or (ac["headlines"][0][:50] if ac.get("headlines") else "")
                or f"Ad {idx + 1}"
            )
            with st.expander(f"📋 Ad {idx + 1} — {label}", expanded=(idx == 0)):
                render_scorecard(res, account_type_r, platform_r, audit_mode_r)
                st.markdown("---")
                html = generate_html_report(
                    res, account_type_r, platform_r, audit_mode_r,
                    ac, canva_url_r, brand_name_r,
                )
                st.download_button(
                    f"⬇️ Download Report — Ad {idx + 1}",
                    data=html,
                    file_name=f"audit_ad{idx+1}_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html",
                    key=f"dl_{idx}",
                    use_container_width=True,
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
