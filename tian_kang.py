import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 系統常數與分頁設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET, EMP_SHEET, INS_SHEET = "salary_data", "emp_info", "ins_info"
ACC_SHEET, LOCK_SHEET = "user_accounts", "lock_status"
LEAVE_SHEET, OT_SHEET = "leave_requests", "ot_requests"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心邏輯定義 (藥局/個管師欄位隔離) ---
PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))

LEAVE_TYPES = {
    "特休": {"pay_ratio": 0.0, "deduct_balance": "剩餘特休時數"},
    "補休": {"pay_ratio": 0.0, "deduct_balance": "補休餘額"},
    "病假(半薪)": {"pay_ratio": 0.5}, "生理假(半薪)": {"pay_ratio": 0.5},
    "事假(無薪)": {"pay_ratio": 1.0}, "婚假(全薪)": {"pay_ratio": 0.0},
    "產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend"},
    "育嬰留職停薪(無薪)": {"pay_ratio": 1.0}
}

# --- 3. 工具函數 ---
def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()
def clean_val(v):
    try: return float(v) if v and str(v).strip() != "" else 0.0
    except: return 0.0

def get_seniority(start_date_str):
    if not start_date_str or str(start_date_str) == "N/A": return 0
    try:
        sd = pd.to_datetime(start_date_str)
        return max(0, (datetime.now() - sd).days / 365.25)
    except: return 0

def robust_clean(df, mapping_dict=None):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    if mapping_dict:
        new_cols = {c: mapping_dict[k] for c in df.columns for k in mapping_dict if k in c}
        df = df.rename(columns=new_cols)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

def generate_bank_csv(df_source, df_employee):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def send_salary_email(to_email, name, month, details_dict):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康管理部 <{S_EMAIL}>"; msg["To"] = to_email
    msg["Subject"] = f"【薪資通知】{month} 薪資明細 - {name}"
    rows = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    html = f"<html><body><h3>👋 {name} 同仁您好：</h3><table style='border-collapse:collapse; width:100%; max-width:450px;'>{rows}</table></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg); return True
    except: return False

# --- 4. 數據讀取與快取 ---
@st.cache_data(ttl=60)
def fetch_all_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    std_map = {"月份": "月份", "姓名": "姓名", "身分證": "身分證", "加保日期": "加保日期", "補休餘額": "補休餘額", "加班時薪": "加班時薪", "基本薪資合計": "基本薪資合計", "單位": "單位"}
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=0), std_map)
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=0), std_map)
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=0), std_map)
    df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=0))
    df_lv = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=0))
    df_ot = robust_clean(conn.read(worksheet=OT_SHEET, ttl=0))
    try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=0))
    except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
    return df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock

def main():
    st.title("🚀 天康藥局雲端管理系統")
    if st.sidebar.button("🔄 刷新雲端資料"): st.cache_data.clear(); st.rerun()

    try:
        df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock = fetch_all_data()
    except Exception as e: st.error(f"連線失敗: {e}"); st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("入口", ["管理登入", "員工查詢", "註冊"], horizontal=True)
        if mode == "管理登入":
            acc = st.text_input("帳號"); pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
        elif mode == "員工查詢":
            e_acc = st.text_input("查詢帳號"); e_pw = st.text_input("查詢密碼", type="password")
            if st.button("登入查詢"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # --- 員工專區 ---
        name = st.session_state.user_name.replace(" ", "")
        st.subheader(f"👋 {name} 同仁")
        t1, t2 = st.tabs(["💰 薪資單", "📅 加班/請假申請"])
        with t1: st.dataframe(df_pay[df_pay['姓名'] == name])
        with t2:
            st.metric("補休餘額", f"{clean_val(df_emp[df_emp['姓名']==name].iloc[0].get('補休餘額',0)) if not df_emp[df_emp['姓名']==name].empty else 0} hr")
            with st.form("apply_f"):
                lt = st.selectbox("申請項目", list(LEAVE_TYPES.keys()) + ["加班預約", "補休轉薪資"]); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 12.0, 1.0, 0.5), st.text_area("理由")
                if st.form_submit_button("送出"):
                    if "加班" in lt: st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["累積補休"],"原因":[lr],"狀態":["待審核"]})], ignore_index=True))
                    elif "薪資" in lt: st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["換錢"],"原因":["補休轉錢"],"狀態":["待審核"]})], ignore_index=True))
                    else: st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True))
                    st.cache_data.clear(); st.success("已提交")
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else: # --- 管理端 ---
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()
        
        # 💡 店長權限「物理隔離」✅
        if role == 3: t_titles = ["💰 薪資發薪作業"]
        else: t_titles = ["💰 薪資發薪作業", "📑 申請單審核中心", "👤 員工主資料維護", "🏥 勞健保紀錄", "🔑 帳號維護"]
        tabs = st.tabs(t_titles)

        # --- 分頁 0: 薪資發薪作業 (含藥局/個管師分類) ---
        with tabs[0]:
            all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if '月份' in df_pay.columns else ["無"]
            target_m = st.sidebar.selectbox("月份切換", all_m, key="m_box")
            is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
            
            # 💡 老闆管理選單回歸 ✅
            if role == 1:
                with st.sidebar.expander("🛠️ 月份管理 (新增/刪除)"):
                    new_m = st.text_input("新增 (YYYY-MM)", "2026-06")
                    if st.button("🚀 執行建立"):
                        l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                        new_r = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                        for c in ALL_VAR_COLS: new_r[c] = 0
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                    if st.button("🔒 鎖定/🔓 解鎖"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=LOCK_SHEET, data=pd.concat([df_lock[df_lock['月份'].astype(str) != target_m], pd.DataFrame({"月份":[target_m],"狀態":["OPEN" if is_locked else "LOCKED"]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                    if st.button("🔥 刪除月份") and st.checkbox("確認"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != target_m]); st.cache_data.clear(); st.rerun()

            curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
            if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
            
            if role == 1: # 老闆視角 (含 應付金額 計算)
                curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼','電子郵件','加班時薪']], on='姓名', how='left')
                # 計算應付總額
                l_ins_list = []
                for n in curr['姓名']:
                    v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                    l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名','勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n,0], index=['姓名','勞健保個人負擔']))
                curr = curr.merge(pd.DataFrame(l_ins_list), on='姓名', how='left')
                for c in ALL_VAR_COLS + ['基本薪資合計','勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                curr['應付金額'] = (curr['基本薪資合計'] + clean_val(curr.get('執照津貼',0)) + clean_val(curr.get('車資補貼',0)) + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                
                st.subheader("💊 藥局組")
                ed_phar = st.data_editor(curr[curr['單位'] == "藥局"][['月份','店別','姓名','基本薪資合計','應付金額','電子郵件'] + PHARMACY_VAR + ['備註']], key="ed_p")
                st.subheader("📂 個管師組")
                ed_case = st.data_editor(curr[curr['單位'] == "個管師"][['月份','店別','姓名','基本薪資合計','應付金額','電子郵件'] + CASE_MGR_VAR + ['備註']], key="ed_c")
                
                if st.button("💾 老闆同步存檔"):
                    final_df = pd.concat([ed_phar, ed_case])
                    for _, r in final_df.iterrows():
                        for col in final_df.columns:
                            if col in ALL_VAR_COLS or col == "備註": df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == r['姓名']), col] = r[col]
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay); st.success("OK")
                
                # 網銀與 Email ✅
                c1, c2, c3 = st.columns(3)
                with c1: st.download_button("📥 藥局 CSV", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp), f"Phar_{target_m}.csv")
                with c2: st.download_button("📥 個管師 CSV", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp), f"Case_{target_m}.csv")
                with c3:
                    if st.button("📧 批量寄送 Email"):
                        for _, r in final_df.iterrows():
                            if not pd.isna(r.get('電子郵件')): send_salary_email(r['電子郵件'], r['姓名'], target_m, {"實領總額": r.get('應付金額', 0)})
                        st.success("✅ 完成")
            
            else: # 💡 店長視角 (去識別化 + 加班時數轉換 ✅)
                mgr_v = curr.merge(df_emp[['姓名','單位']], on='姓名', how='left')
                disp_l = []
                for _, r in mgr_v.iterrows():
                    rate = clean_val(df_emp[df_emp['姓名'] == r['姓名']].iloc[0].get('加班時薪', 0))
                    r['加班時數'] = round(clean_val(r['加班津貼']) / rate, 2) if rate > 0 else 0.0; disp_l.append(r)
                f_mgr = pd.DataFrame(disp_l)
                # 分類顯示
                st.subheader("💊 藥局發薪編輯")
                e_p = st.data_editor(f_mgr[f_mgr['單位'] == "藥局"][["月份","店別","姓名"] + [c for c in PHARMACY_VAR if c != "加班津貼"] + ["加班時數","備註"]], disabled=is_locked, key="mgr_p")
                st.subheader("📂 個管師發薪編輯")
                e_c = st.data_editor(f_mgr[f_mgr['單位'] == "個管師"][["月份","店別","姓名"] + [c for c in CASE_MGR_VAR if c != "加班津貼"] + ["加班時數","備註"]], disabled=is_locked, key="mgr_c")
                
                if st.button("💾 店長同步存檔") and not is_locked:
                    for _, row in pd.concat([e_p, e_c]).iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                        df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), '加班津貼'] = round(clean_val(row['加班時數']) * rate)
                        for col in row.index:
                            if col in ALL_VAR_COLS and col != "加班時數": df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), col] = row[col]
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay); st.success("OK")

        # --- 其餘分頁 (店長不可見 ✅) ---
        if role == 1:
            with tabs[1]: # 審核
                c1, c2 = st.columns(2)
                with c1:
                    p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                    for idx, row in p_l.iterrows():
                        if st.button(f"✅ 核准 {row['姓名']} 的 {row['類別']}", key=f"la_{idx}"):
                            rule = LEAVE_TYPES.get(row['類別'], {})
                            if rule.get('deduct_balance') in df_emp.columns:
                                df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                            df_lv.at[idx, '狀態'] = '已核准'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=df_lv); st.cache_data.clear(); st.rerun()
                with c2:
                    p_o = df_ot[df_ot['狀態'] == '待審核'] if '狀態' in df_ot.columns else pd.DataFrame()
                    for idx, row in p_o.iterrows():
                        if st.button(f"✅ 同意 {row['姓名']} 的 {row['處理方式']}", key=f"oa_{idx}"):
                            if row['處理方式'] == '累積補休': df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                            else:
                                rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                                t_idx = df_pay.index[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名'])]
                                if not t_idx.empty:
                                    df_pay.at[t_idx[0], '加班津貼'] = clean_val(df_pay.at[t_idx[0], '加班津貼']) + round(rate * clean_val(row['時數']))
                                    df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] -= clean_val(row['時數'])
                                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay)
                            df_ot.at[idx, '狀態'] = '已執行'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=df_ot); st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.rerun()

            with tabs[2]: st.data_editor(df_emp, num_rows="dynamic", key="b_main") # 員工主表
            with tabs[3]: st.data_editor(df_ins, num_rows="dynamic", key="b_ins") # 勞健保紀錄
            with tabs[4]: st.dataframe(df_acc, use_container_width=True) # 帳號維護

if __name__ == "__main__":
    main()
