import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 雲端設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts"
LOCK_SHEET = "lock_status"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. Email 發送核心函數 (承瑋大助專屬金鑰) ---
def send_salary_email(to_email, name, month, unit, details_dict):
    SENDER_EMAIL = "a10019990@gmail.com"
    SENDER_PASSWORD = "aczy dkos wjnd cgkm" 

    message = MIMEMultipart()
    message["From"] = f"天康連鎖藥局管理部 <{SENDER_EMAIL}>"
    message["To"] = to_email
    message["Subject"] = f"【薪資通知】{month} 月份薪資明細 - {name}"

    rows_html = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v} 元</td></tr>" if "元" not in str(v) and isinstance(v, (int, float)) else f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    
    html = f"""
    <html>
    <body style="font-family: 'Microsoft JhengHei', sans-serif; color: #333;">
        <h2 style="color: #2c5f2d;">👋 {name} 同仁您好：</h2>
        <p>這是您在 <b>{month}</b> 月份的薪資明細，請核對：</p>
        <table style="border-collapse: collapse; width: 100%; max-width: 450px; font-size: 15px;">
            {rows_html}
        </table>
        <p style="color: #d32f2f; font-weight: bold; margin-top: 15px;">* 如有任何疑問，請於三日內回報管理部，謝謝。 *</p>
        <hr style="border: 0; border-top: 1px solid #eee; margin-top: 30px;">
        <p style="color: #999; font-size: 11px;">此郵件由天康管理系統自動發出，請勿直接回覆。</p>
    </body>
    </html>
    """
    message.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(message)
        return True, "成功"
    except Exception as e:
        return False, str(e)

# --- 3. 核心工具 ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def clean_val(v):
    try: return float(v) if v and str(v).strip() != "" else 0.0
    except: return 0.0

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {
        "月份": "月份", "生效月份": "生效月份", "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數", "電子郵件": "電子郵件",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期",
        "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計",
        "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "收款帳號": "收款帳號", "狀態": "狀態"
    }
    new_mapping = {c: mapping[k] for c in df.columns for k in mapping if k in c}
    df = df.rename(columns=new_mapping)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

def generate_bank_csv(df_source, df_employee, target_m):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 ")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新資料"):
        st.cache_data.clear(); st.rerun()

    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))
    INS_COLS = ['生效月份', '姓名', '身分證', '勞保', '健保', '健保人數', '勞健保個人負擔', '加保日期']

    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=300), expected_cols=['姓名', '單位', '店別', '身分證', '電子郵件', '基本薪資合計', '執照津貼', '車資補貼'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=300), expected_cols=['月份', '店別', '姓名', '備註'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=300), expected_cols=INS_COLS)
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=300))
        try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=300), expected_cols=['月份', '狀態'])
        except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
    except Exception as e: st.error(f"雲端讀取失敗: {e}"); st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["管理端登入", "員工薪資查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("帳號"); pw = st.text_input("密碼", type="password")
            if st.button("登入後台"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): 
                        sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
                else: st.error("❌ 帳密錯誤")
        elif mode == "員工薪資查詢":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not match.empty:
                    # 💡 修正關鍵：員工登入也要給予 shop 變數，防止 Attribute Error
                    st.session_state.auth = 5
                    st.session_state.user_name = match.iloc[0]['姓名']
                    st.session_state.shop = "PERSONAL" 
                    st.rerun()
        elif mode == "新帳號註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("註冊"):
                    new_u = pd.DataFrame({"姓名":[n.replace(" ","")], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})
                    conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                    st.cache_data.clear(); st.success("註冊成功")
        return

    # 💡 這裡現在不會再報錯了
    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # 員工專區
        name = st.session_state.user_name.replace(" ", "")
        st.subheader(f"👋 {name} 同仁，您的薪資明細")
        emp_m = df_emp[df_emp['姓名'] == name]
        if not emp_m.empty:
            emp_info = emp_m.iloc[0]; unit = str(emp_info['單位']).strip()
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            ins_rows = []
            for m in p_pay['月份'].astype(str):
                v_ins = df_ins[(df_ins['姓名'] == name) & (df_ins['生效月份'].astype(str) <= m)]
                ins_rows.append(v_ins.sort_values('生效月份', ascending=False).iloc[0][['勞保','健保','健保人數','勞健保個人負擔']] if not v_ins.empty else pd.Series([0,0,0,0], index=['勞保','健保','健保人數','勞健保個人負擔']))
            p_pay = pd.concat([p_pay.reset_index(drop=True), pd.DataFrame(ins_rows).reset_index(drop=True)], axis=1)
            
            p_pay['基本薪資合計'] = clean_val(emp_info['基本薪資合計'])
            p_pay['執照津貼'] = clean_val(emp_info['執照津貼'])
            p_pay['車資補貼'] = clean_val(emp_info['車資補貼'])
            for c in ALL_VAR_COLS + ['勞保','健保','勞健保個人負擔']: p_pay[c] = p_pay[c].apply(clean_val)
            
            bonus_cols = PHARMACY_VAR if unit == "藥局" else CASE_MGR_VAR
            p_pay['實領總額'] = (p_pay['基本薪資合計'] + p_pay['執照津貼'] + p_pay['車資補貼'] + p_pay[bonus_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
            cols = ['月份', '姓名', '基本薪資合計'] + bonus_cols + ['勞保', '健保', '健保人數', '勞健保個人負擔', '實領總額', '備註']
            st.dataframe(p_pay[[c for c in cols if c in p_pay.columns]])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        if role == 4: # 會計 (排序修正)
            t_acct = st.tabs(["🏥 勞健保明細維護", "👤 全體員工名單"])
            with t_acct[0]:
                e_ins = st.data_editor(df_ins[INS_COLS], num_rows="dynamic", key="ac_ed")
                if st.button("💾 同步更新勞健保"): conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("更新成功")
            with t_acct[1]:
                df_v = df_emp[["店別", "姓名", "單位", "身分證", "電子郵件"]].copy(); df_v['店別'] = df_v['店別'].astype(str)
                st.dataframe(df_v.sort_values("店別"))

        else: # 老闆 與 店長
            tab_titles = ["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄檢視", "🔑 帳號管理"] if role == 1 else ["💰 薪資發薪作業"]
            tabs = st.tabs(tab_titles)
            with tabs[0]:
                all_m_safe = sorted([str(m) for m in df_pay['月份'].dropna().unique() if str(m).strip() != ""], reverse=True)
                target_m = st.sidebar.selectbox("月份切換", all_m_safe if all_m_safe else ["無"], key="tgt_m")
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False

                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理"):
                        nm = st.text_input("建立新月份", "2026-06")
                        if st.button("執行建立"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            df_t = df_emp[['姓名']].merge(l_rem, on='姓名', how='left')
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_t["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/🔓 解鎖本月"):
                            new_s = "OPEN" if is_locked else "LOCKED"
                            others = df_lock[df_lock['月份'].astype(str) != target_m]
                            conn.update(worksheet=LOCK_SHEET, data=pd.concat([others, pd.DataFrame({"月份":[target_m],"狀態":[new_s]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        dm = st.selectbox("刪除月份", all_m_safe, key="del_m")
                        if st.button("🔥 執行刪除") and st.checkbox(f"確認刪除 {dm}"):
                            conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != dm]); st.cache_data.clear(); st.rerun()

                if target_m != "無":
                    l_ins_list = []
                    for n in df_emp['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)]
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0][['姓名', '勞健保個人負擔']] if not v.empty else pd.Series([n, 0], index=['姓名', '勞健保個人負擔']))
                    l_ins = pd.DataFrame(l_ins_list)
                    curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                    if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼','電子郵件']], on='姓名', how='left')
                    curr = curr.merge(l_ins, on='姓名', how='left'); curr = curr.loc[:, ~curr.columns.duplicated()] 
                    for c in ALL_VAR_COLS + ['基本薪資合計', '執照津貼', '車資補貼', '勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']

                    st.subheader(f"📅 {target_m} 薪資核對 ({'🔒 鎖定' if is_locked and role == 3 else '✍️ 編輯'})")
                    uf = st.radio("篩選單位", ["全部", "藥局", "個管師"], horizontal=True) if role == 1 else "全部"
                    disp = curr.copy()
                    if role == 1 and uf != "全部": disp = disp[disp['單位'] == uf]
                    if role == 3: disp = disp[["月份", "店別", "姓名"] + (PHARMACY_VAR if (not disp.empty and disp.iloc[0]['單位']=="藥局") else CASE_MGR_VAR) + ["備註"]]

                    edited = st.data_editor(disp, key="main_edit", disabled=(is_locked and role == 3))
                    if not (is_locked and role == 3) and st.button("💾 同步薪資存檔"):
                        for idx, row in edited.iterrows():
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註":
                                    df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), col] = row[col]
                        conn.update(worksheet=PAY_SHEET, data=df_pay); st.cache_data.clear(); st.success("存檔成功")

                    if role == 1:
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        with c1: st.download_button("📥 藥局網銀檔", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp, target_m), f"Phar_{target_m}.csv")
                        with c2: st.download_button("📥 個管師網銀檔", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp, target_m), f"Case_{target_m}.csv")
                        with c3:
                            if st.button(f"📧 批量發送 {target_m} Email"):
                                sc = 0
                                with st.spinner("傳送中..."):
                                    for _, r in edited.iterrows():
                                        if pd.isna(r['電子郵件']) or "@" not in str(r['電子郵件']): continue
                                        b_cols = PHARMACY_VAR if r['單位']=="藥局" else CASE_MGR_VAR
                                        det = {"基本薪資": r['基本薪資合計'], "執照津貼": r['執照津貼'], "車資補貼": r['車資補貼']}
                                        for b in b_cols: det[b] = r[b]
                                        det.update({"勞健保扣款": f"-{r['勞健保個人負擔']}", "實領總額": r['應付金額'], "備註": r['備註']})
                                        ok, _ = send_salary_email(r['電子郵件'], r['姓名'], target_m, r['單位'], det)
                                        if ok: sc += 1
                                st.success(f"✅ 成功寄出 {sc} 封明細。")

            if role == 1:
                with tabs[1]:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic", key="em_e")
                    if st.button("💾 更新員工資料庫"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
                with tabs[2]: st.dataframe(df_ins[INS_COLS].sort_values(['姓名', '生效月份'], ascending=[True, False]))
                with tabs[3]: st.dataframe(df_acc[["姓名", "帳號", "身分證"]])

if __name__ == "__main__":
    main()
