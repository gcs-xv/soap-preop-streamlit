# -------------------------
# Streamlit UI (Mobile-first)
# -------------------------
st.set_page_config(page_title="SOAP → Pre-Op", layout="centered")
st.title("SOAP Terjaring → SOAP Pre-Op")

# Preset DPJP (boleh tambah)
DPJP_PRESETS = [
    "drg. Husnul Basyar, Sp.B.M.Mf.",
    "drg. Abul Fauzi, Sp.B.M.Mf., Subsp.Tr.Mf.S.Tm.",
    "Dr. drg. Andi Tajrin, M.Kes., Sp.B.M.Mf., Subsp.C.O.Mf.",
]

# Plan library yang GENERIK (biar tidak kaku)
DEFAULT_PLAN_LIBRARY = [
    "ACC TS Anestesi",
    "IVFD (isi sesuai)",
    "Puasa pre-op (isi sesuai)",
    "Sikat gigi sebelum tidur & sebelum ke kamar operasi",
    "Gunakan masker bedah saat ke kamar operasi",
    "Antibiotik profilaksis (isi sesuai)",
    "Siap darah/PRC (jika perlu)",
]

def dedupe_case_insensitive(lines: list[str]) -> list[str]:
    out = []
    seen = set()
    for x in lines:
        k = x.strip().lower()
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out

def parse_if_needed(raw_text: str):
    """Auto-parse whenever raw text changes."""
    if "raw_prev" not in st.session_state:
        st.session_state["raw_prev"] = ""
    if raw_text.strip() and raw_text != st.session_state["raw_prev"]:
        st.session_state["parsed"] = parse_raw_soap(raw_text)
        st.session_state["raw_prev"] = raw_text

def reset_all():
    for k in list(st.session_state.keys()):
        del st.session_state[k]

# Top bar actions
cA, cB = st.columns(2)
with cA:
    if st.button("🔄 Reset", use_container_width=True):
        reset_all()
        st.rerun()
with cB:
    st.caption("Tip: paling enak dipakai di HP — alurnya 1) Paste → 2) Edit → 3) Output")

tab1, tab2, tab3 = st.tabs(["1) Paste", "2) Edit", "3) Output"])

# -------------------------
# TAB 1: Paste
# -------------------------
with tab1:
    st.subheader("Paste SOAP mentah")
    raw = st.text_area(
        "Tempel SOAP Rawat Jalan / non pre-op di sini",
        height=260,
        placeholder="Contoh: Assalamualaikum... (Rawat Jalan)...\nTn./Ny./An. ... / L/P / ...\nS: ...\nO: ...\nA: ...\nP: ...\nResiden: ...\nDPJP: ..."
    )

    st.subheader("Opsional: paste hasil LAB (biar auto masuk penunjang)")
    lab_text = st.text_area(
        "Blok lab (boleh apa aja formatnya, yang penting ada KEY: VALUE)",
        height=140,
        placeholder="Contoh:\nLab Darah (30/12/2025)\nWBC : ...\nRBC : ...\nCT : ...\nBT : ...\nGDS : ...\nHBsAg : ...\nKesan : ..."
    )

    parse_if_needed(raw)

    # Optional parse ulang button
    if st.button("Parse ulang", type="primary", use_container_width=True):
        if raw.strip():
            st.session_state["parsed"] = parse_raw_soap(raw)
            st.session_state["raw_prev"] = raw
            st.success("Berhasil parse.")
        else:
            st.warning("SOAP mentah masih kosong.")

    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))

    with st.expander("Lihat hasil parse (preview singkat)"):
        st.write("**Nama:**", parsed.nama or "-")
        st.write("**RM:**", parsed.rm or "-")
        st.write("**Residen:**", parsed.residen or "-")
        st.write("**DPJP:**", parsed.dpjp or "-")
        st.write("**Penunjang terdeteksi:**")
        st.write("\n".join([f"- {x}" for x in (parsed.penunjang_items or [])]) or "-")

# -------------------------
# TAB 2: Edit (simple phone form)
# -------------------------
with tab2:
    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))

    st.subheader("Identitas")
    nama = st.text_input("Nama (Tn./Ny./An.)", value=parsed.nama or "")
    jk = st.text_input("JK", value=parsed.jk or "")
    umur = st.text_input("Umur", value=parsed.umur or "")
    pembiayaan = st.text_input("Pembiayaan", value=parsed.pembiayaan or "BPJS")
    jenis_perawatan = st.text_input("Jenis perawatan", value="Rawat Inap")
    kamar = st.text_input("Kamar/Bed", value=parsed.kamar or "")

    rm = st.text_input("RM", value=parsed.rm or "")
    rs = st.text_input("RS", value=parsed.rs or "RSGMP UNHAS")

    st.divider()

    st.subheader("Jadwal operasi (otomatis H+1, bisa diganti)")
    today = datetime.now(TZ).date()
    default_op = today + timedelta(days=1)

    tanggal_laporan = st.date_input("Tanggal laporan", value=today)
    tanggal_operasi = st.date_input("Tanggal operasi", value=default_op)

    c1, c2 = st.columns(2)
    with c1:
        jam_operasi = st.text_input("Jam operasi", value="08.00")
    with c2:
        zona_waktu = st.text_input("Zona waktu", value="WITA")

    anestesi = st.text_input("Anestesi", value="general anestesi")
    tindakan_line = st.text_input(
        "Tindakan (bebas, tanpa tanggal/jam)",
        value=""
    )

    st.divider()

    st.subheader("Isi SOAP (auto dari mentah, kamu bisa edit)")
    S = st.text_area("S", value=parsed.S or "", height=140)
    O_generalis = st.text_area("O - Status Generalis", value=parsed.O_generalis or "", height=120)
    EO = st.text_area("EO", value=parsed.EO or "", height=120)
    IO = st.text_area("IO", value=parsed.IO or "", height=120)
    A = st.text_area("A", value=parsed.A or "", height=100)

    st.divider()

    st.subheader("Pemeriksaan Penunjang (bebas & fleksibel)")
    # Merge: parsed penunjang + lab items (kalau user isi lab_text di tab1)
    lab_text = st.session_state.get("lab_text_cache", "")
    # cache lab from tab1 to tab2/tab3
    # (kalau belum ada, ambil dari widget tab1 via session_state kalau tersedia)
    if "lab_text_cache" not in st.session_state:
        st.session_state["lab_text_cache"] = ""

    # try to read latest lab text from tab1 if user already typed there
    # (Streamlit state untuk widget beda tab bisa tricky; simplest: user paste lagi di tab1 bila perlu)
    # We'll still allow manual penunjang edit below.

    base_pen = list(parsed.penunjang_items or [])
    # If user pasted lab_text in tab1, we can re-derive from raw session state if present
    # We can't reliably read tab1 widget value here, so we provide a lab paste box also here:
    lab_text2 = st.text_area(
        "Opsional: paste hasil lab di sini juga (biar auto jadi item penunjang)",
        height=120,
        placeholder="Paste lab (kalau belum paste di tab 1) ..."
    )
    lab_items = lab_block_to_items(lab_text2) if lab_text2.strip() else []
    merged_pen = dedupe_case_insensitive(base_pen + lab_items)

    penunjang_editor = st.text_area(
        "1 baris = 1 item penunjang (contoh: OPG X-Ray (tanggal), Thorax X-Ray (tanggal), CT/BT, dll)",
        value="\n".join(merged_pen),
        height=160
    )
    penunjang_items = dedupe_case_insensitive([x for x in penunjang_editor.splitlines() if x.strip()])

    st.divider()

    st.subheader("Plan (tinggal pilih + tambah sendiri)")
    picked = st.multiselect(
        "Centang plan umum (boleh edit di bawah)",
        options=DEFAULT_PLAN_LIBRARY,
        default=["ACC TS Anestesi", "Sikat gigi sebelum tidur & sebelum ke kamar operasi", "Gunakan masker bedah saat ke kamar operasi"],
    )

    custom_plan = st.text_area(
        "Tambahan plan (1 baris = 1 item, bebas)",
        height=120,
        placeholder="Contoh:\nIVFD RL 20 tpm (makrodrips)\nPuasa mulai 01.30 WITA\nAntibiotik profilaksis Ceftriaxone inj 1 gr jam 06.30 WITA\nSiap darah 1 bag PRC"
    )

    # Final plan lines: picked + custom lines
    plan_lines = picked + [x.strip() for x in custom_plan.splitlines() if x.strip()]

    st.divider()

    st.subheader("Residen & DPJP")
    st.caption("Residen selalu berbeda-beda — paste aja. Nanti otomatis dirapihin jadi koma-koma.")
    residen_in = st.text_area(
        "Residen",
        value=parsed.residen or "",
        height=80,
        placeholder="Contoh: drg. Reza, drg. Mike, drg. Amal"
    )
    residen_out = split_residen_text(residen_in)

    dpjp_choice = st.selectbox("DPJP (preset)", DPJP_PRESETS, index=0)
    dpjp_custom = st.text_input("DPJP (kalau mau override)", value=parsed.dpjp or "")
    dpjp_final = dpjp_custom.strip() if dpjp_custom.strip() else dpjp_choice

    # Store edited data to session for Output tab
    st.session_state["edited"] = {
        "nama": nama, "jk": jk, "umur": umur, "pembiayaan": pembiayaan,
        "jenis_perawatan": jenis_perawatan, "kamar": kamar, "rm": rm, "rs": rs,
        "tanggal_laporan": tanggal_laporan, "tanggal_operasi": tanggal_operasi,
        "jam_operasi": jam_operasi, "zona_waktu": zona_waktu,
        "anestesi": anestesi, "tindakan_line": tindakan_line,
        "S": S, "O_generalis": O_generalis, "EO": EO, "IO": IO, "A": A,
        "penunjang_items": penunjang_items,
        "plan_lines": plan_lines,
        "residen": residen_out,
        "dpjp": dpjp_final,
    }

    st.success("✅ Sudah siap. Lanjut ke tab 3) Output.")

# -------------------------
# TAB 3: Output
# -------------------------
with tab3:
    st.subheader("Output SOAP Pre-Op")
    parsed = st.session_state.get("parsed", ParsedSoap(penunjang_items=[]))
    edited = st.session_state.get("edited")

    if not edited:
        st.info("Isi dulu di tab 2) Edit, lalu balik ke sini.")
    else:
        # Build a new ParsedSoap with edited content
        p2 = ParsedSoap(
            sapaan=parsed.sapaan,
            pembuka=parsed.pembuka,
            rs=edited["rs"],
            nama=edited["nama"],
            jk=edited["jk"],
            umur=edited["umur"],
            pembiayaan=edited["pembiayaan"],
            jenis_perawatan=edited["jenis_perawatan"],
            kamar=edited["kamar"],
            rm=edited["rm"],
            S=edited["S"],
            O_generalis=edited["O_generalis"],
            EO=edited["EO"],
            IO=edited["IO"],
            penunjang_items=edited["penunjang_items"],
            A=edited["A"],
            residen=edited["residen"],
            dpjp=edited["dpjp"],
        )

        output = build_preop(
            p=p2,
            tanggal_laporan=edited["tanggal_laporan"],
            tanggal_operasi=edited["tanggal_operasi"],
            jam_operasi=edited["jam_operasi"],
            zona_waktu=edited["zona_waktu"],
            tindakan_line=edited["tindakan_line"] or "(isi tindakan)",
            anestesi=edited["anestesi"],
            pembiayaan=edited["pembiayaan"],
            jenis_perawatan=edited["jenis_perawatan"],
            kamar=edited["kamar"] or "(isi kamar/bed)",
            penunjang_items=edited["penunjang_items"],
            plan_items=edited["plan_lines"],
            residen=edited["residen"] or "-",
            dpjp=edited["dpjp"] or "-",
        )

        st.text_area("SOAP Pre-Op (siap copy)", value=output, height=520)

        st.download_button(
            "Download .txt",
            data=output.encode("utf-8"),
            file_name="soap_preop.txt",
            mime="text/plain",
            use_container_width=True,
        )
