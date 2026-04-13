import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 系統常數與分頁定義 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET, EMP_SHEET, INS_SHEET = "salary_data", "emp_info", "ins_info"
ACC_SHEET, LOCK_SHEET = "user_accounts", "lock_status"
LEAVE_SHEET, OT_SHEET = "leave_requests", "ot_requests"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心邏輯：勞基法規則 ---
LEAVE_TYPES = {
    "特休": {"pay_ratio": 0.0, "deduct_balance": "剩餘特休時數"},
    "補休": {"pay_ratio": 0.0, "deduct_balance": "補休餘額"},
    "病假(半薪)": {"pay_ratio": 0.5},
    "生理假(半薪)": {"pay_ratio": 0.5},
    "事假(無薪)": {"pay_ratio": 1.0},
    "家庭照顧假(無薪)": {"pay_ratio": 1.0},
    "婚假(全薪)": {"pay_ratio": 0.0},
    "喪假(全薪)": {"pay_ratio": 0.0},
    "產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend"},
    "流產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend"},
    "產檢假(全薪)": {"pay_ratio": 0.0},
    "陪產檢及陪產假(全薪)": {"pay_ratio": 0.0},
    "育嬰留職停薪(無薪)": {"pay_ratio": 1.0}
}

# --- 3. 核心工具函數 ---
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

def get_labor_law_special_leave(years):
    if years < 0.5: return 0
    elif years < 1: return 3
    elif years < 2: return 7
    elif years < 3: return 10
    elif years < 5: return 14
    else: return min(30, 15 + int(years - 9))

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {
        "生效月份": "生效月份", "月份": "月份", "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數", "電子郵件": "電子郵件",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期", "補休餘額": "補休餘額",
        "剩餘特休時數": "剩餘特休時數", "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計", 
        "加班時薪": "加班時薪", "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", 
        "狀態": "狀態", "類別": "類別", "時數": "時數", "日期": "日期", "原因": "原因", "處理方式": "處理方式", "收款帳號": "收款帳號", "加班津貼": "加班津貼"
    }
    new_cols = {}
    for c in df.columns:
        for k, v in mapping.items():
            if k in c: new_cols[c] = v; break
    df = df.rename(columns=new_cols)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

# 💡 網銀標籤保全 (一向不漏)
def generate_bank_csv(df_source, df_employee):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

# 📧 Email 批量寄送保全
def send_salary_email(to_email, name, month, details_dict):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康管理部 <{S_EMAIL}>"; msg["To"] = to_email
    msg["Subject"] = f"【薪資通知】{month} 薪資明細 - {name}"
    rows = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v} 元</td></tr>" if isinstance(v, (int, float)) else f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    html = f"<html><body><h3>👋 {name} 您好：</h3><p>這是您 {month} 的薪資明細：</p><table style='border-collapse:collapse; width:100%; max-width:450px;'>{rows}</table></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg); return True
    except: return False

# --- 4. 數據讀取與智慧快取 ---
@st.cache_data(ttl=60)
def fetch_all_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=0))
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=0))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=0))
    df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=0))
    df_lv = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=0))
    df_ot = robust_clean(conn.read(worksheet=OT_SHEET, ttl=0))
    try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=0))
    except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
    return df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock

def main():
    st.title("🚀 天康連鎖藥局 - 薪資差勤一體化管理系統")
    if st.sidebar.button("🔄 刷新雲端資料"): st.cache_data.clear(); st.rerun()

    try:
        df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock = fetch_all_data()
    except Exception as e: st.error(f"連線失敗: {e}"); st.stop()

    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))

    if 'auth' not in st.session_state:
        mode = st.radio("入口", ["管理端登入", "員工查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("管理帳號"); pw = st.text_input("管理密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): 
                        sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
        elif mode == "員工查詢":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("查詢登入"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        elif mode == "新帳號註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("執行註冊"):
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=ACC_SHEET, data=pd.concat([df_acc, pd.DataFrame({"姓名":[n.replace(" ","")], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})], ignore_index=True))
                    st.cache_data.clear(); st.success("註冊成功")
        return

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 5. 員工專區 (保全顯示邏輯) ---
    if role == 5:
        name = st.session_state.user_name.replace(" ", "")
        p_ins = df_ins[df_ins['姓名'] == name]
        s_date = str(p_ins.sort_values('加保日期').iloc[0]['加保日期']) if not p_ins.empty else "N/A"
        yrs = get_seniority(s_date); e_info = df_emp[df_emp['姓名'] == name].iloc[0] if not df_emp[df_emp['姓名'] == name].empty else {}
        
        st.subheader(f"👋 {name} 同仁")
        st.sidebar.info(f"🎖️ 年資：{yrs:.2f} 年\n🗓️ 加保：{s_date}\n🎁 法定特休：{get_labor_law_special_leave(yrs)} 天")

        t1, t2, t3 = st.tabs(["💰 薪資單查詢", "📅 加班與請假申請", "🔍 差勤紀錄明細"])
        with t1:
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            if not p_pay.empty:
                ins_rows = []
                for m in p_pay['月份'].astype(str):
                    v_ins = df_ins[(df_ins['姓名'] == name) & (df_ins['生效月份'].astype(str) <= m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                    ins_rows.append(v_ins.sort_values('生效月份', ascending=False).iloc[0].reindex(['勞保','健保','勞健保個人負擔'], fill_value=0) if not v_ins.empty else pd.Series([0,0,0], index=['勞保','健保','勞健保個人負擔']))
                p_pay = pd.concat([p_pay.reset_index(drop=True), pd.DataFrame(ins_rows).reset_index(drop=True)], axis=1)
                for c in ALL_VAR_COLS + ['勞保','健保','勞健保個人負擔']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
                b_cols = PHARMACY_VAR if (e_info.get('單位') == "藥局") else CASE_MGR_VAR
                p_pay['實領總額'] = (clean_val(e_info.get('基本薪資合計',0)) + clean_val(e_info.get('執照津貼',0)) + clean_val(e_info.get('車資補貼',0)) + p_pay[b_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
                st.dataframe(p_pay[['月份', '姓名'] + b_cols + ['勞保', '健保', '勞健保個人負擔', '實領總額', '備註']])
            else: st.warning("目前無發薪紀錄。")

        with t2:
            c1, c2 = st.columns(2)
            with c1:
                st.metric("補休餘額", f"{clean_val(e_info.get('補休餘額',0))} hr")
                with st.form("l_f"):
                    lt = st.selectbox("假別", list(LEAVE_TYPES.keys())); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 8.0, 1.0, 0.5), st.text_area("理由")
                    if st.form_submit_button("送出申請"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True)); st.cache_data.clear(); st.success("已送審")
                st.divider()
                with st.form("p_f"):
                    st.markdown("### 💵 補休轉現金")
                    ph = st.number_input("小時", 0.5, clean_val(e_info.get('補休餘額',0)), 1.0, 0.5)
                    if st.form_submit_button("申請"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(datetime.now().date())],"姓名":[name],"時數":[ph],"處理方式":["換錢"],"原因":["補休核現"],"狀態":["待審核"]})], ignore_index=True)); st.cache_data.clear(); st.success("已送出")
            with c2:
                with st.form("ot_f"):
                    st.markdown("### ⚡ 加班預約")
                    od, oh, orsn = st.date_input("加班日期"), st.number_input("預計小時", 0.5, 12.0, 1.0, 0.5), st.text_area("原因")
                    if st.form_submit_button("預約加班"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(od)],"姓名":[name],"時數":[oh],"處理方式":["累積補休"],"原因":[orsn],"狀態":["待審核"]})], ignore_index=True)); st.cache_data.clear(); st.success("預約成功")

        with t3:
            st.write("🌿 請假單紀錄"); st.dataframe(df_lv[df_lv['姓名']==name], use_container_width=True)
            st.write("⚡ 加班與換錢紀錄"); st.dataframe(df_ot[df_ot['姓名']==name], use_container_width=True)
        if st.sidebar.button("安全登出"): del st.session_state['auth']; st.rerun()

    # --- 6. 管理端 (老闆/店長/會計) ---
    else:
        if st.sidebar.button("安全登出"): del st.session_state['auth']; st.rerun()
        
        if role == 4: # 會計 (保全 8 欄位)
            st.subheader("會計維護中心")
            e_in = st.data_editor(df_ins, num_rows="dynamic")
            if st.button("💾 更新資料"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=INS_SHEET, data=e_in); st.cache_data.clear(); st.success("OK")

        else: # 老闆 與 店長
            tabs = st.tabs(["💰 薪資發薪作業", "📑 申請單審核中心", "👤 員工主資料", "🏥 勞健保明細", "🔑 帳號維護"])
            
            with tabs[0]: # 薪資作業
                all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if '月份' in df_pay.columns else ["無"]
                target_m = st.sidebar.selectbox("月份", all_m, key="m_box")
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
                
                # 💡 月份管理復原 ✅
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理 (建立/刪除/鎖定)"):
                        new_m = st.text_input("新增月份 (YYYY-MM)", "2026-06")
                        if st.button("🚀 執行建立"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            new_r = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/🔓 解鎖"):
                            new_s = "OPEN" if is_locked else "LOCKED"; others = df_lock[df_lock['月份'].astype(str) != target_m]
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=LOCK_SHEET, data=pd.concat([others, pd.DataFrame({"月份":[target_m],"狀態":[new_s]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        del_m = st.selectbox("選取刪除月份", all_m, key="del_box")
                        if st.button("🔥 執行刪除") and st.checkbox(f"確認刪除 {del_m}"):
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m]); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
                
                if role == 1: # 老闆視角：保全總額與 Email
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼','電子郵件','加班時薪']], on='姓名', how='left')
                    l_ins_list = []
                    for n in curr['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名','勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n,0], index=['姓名','勞健保個人負擔']))
                    curr = curr.merge(pd.DataFrame(l_ins_list), on='姓名', how='left')
                    for c in ALL_VAR_COLS + ['基本薪資合計','勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + clean_val(curr['執照津貼']) + clean_val(curr['車資補貼']) + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                    edited = st.data_editor(curr, key="boss_pay_final")
                    # 📧 Email 按鈕與網銀下載
                    c1, c2, c3 = st.columns(3)
                    with c1: st.download_button("📥 藥局網銀", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp), f"Phar_{target_m}.csv")
                    with c2: st.download_button("📥 個管師網銀", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp), f"Case_{target_m}.csv")
                    with c3:
                        if st.button("📧 批量寄送 Email 明細"):
                            for _, r in edited.iterrows():
                                if not pd.isna(r.get('電子郵件')): send_salary_email(r['電子郵件'], r['姓名'], target_m, {"應付總額": r.get('應付金額', 0), "備註": r.get('備註','')})
                            st.success("✅ 完成")
                else: # 💡 店長視角 (隱私保全)
                    mgr_v = curr.merge(df_emp[['姓名','單位']], on='姓名', how='left')
                    disp_l = []
                    for _, r in mgr_v.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == r['姓名']].iloc[0].get('加班時薪', 0))
                        r['加班時數'] = round(clean_val(r['加班津貼']) / rate, 2) if rate > 0 else 0.0; disp_l.append(r)
                    final_mgr = pd.DataFrame(disp_l); b_cols = PHARMACY_VAR if (not final_mgr.empty and final_mgr.iloc[0].get('單位') == "藥局") else CASE_MGR_VAR
                    edited = st.data_editor(final_mgr[["月份","店別","姓名"] + [c for c in b_cols if c != "加班津貼"] + ["加班時數","備註"]], disabled=is_locked)

                if st.button("💾 同步存檔") and not (is_locked and role == 3):
                    for idx, row in edited.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                        if role == 3: df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), '加班津貼'] = round(clean_val(row['加班時數']) * rate)
                        else:
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註": df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), col] = row[col]
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay); st.cache_data.clear(); st.success("OK")

            with tabs[1]: # 💡 審核中心：加班與換錢
                if role == 1:
                    c1, c2 = st.columns(2)
                    with c1:
                        p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                        for idx, row in p_l.iterrows():
                            with st.expander(f"🌿 {row.get('姓名')} - {row.get('類別')}"):
                                if st.button("✅ 核准假單", key=f"la_{idx}"):
                                    rule = LEAVE_TYPES.get(row['類別'], {})
                                    if rule.get('deduct_balance') in df_emp.columns:
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                    df_lv.at[idx, '狀態'] = '已核准'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=df_lv); st.cache_data.clear(); st.rerun()
                    with c2:
                        p_o = df_ot[df_ot['狀態'] == '待審核'] if '狀態' in df_ot.columns else pd.DataFrame()
                        for idx, row in p_o.iterrows():
                            with st.expander(f"⚡ {row.get('姓名')} - {row.get('處理方式')} ({row.get('時數')}hr)"):
                                if st.button("✅ 同意執行", key=f"oa_{idx}"):
                                    if row['處理方式'] == '累積補休':
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                    else: # 換錢：扣補休、加加班費
                                        rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                                        t_idx = df_pay.index[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名'])]
                                        if not t_idx.empty:
                                            df_pay.at[t_idx[0], '加班津貼'] = clean_val(df_pay.at[t_idx[0], '加班津貼']) + round(rate * clean_val(row['時數']))
                                            df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] -= clean_val(row['時數'])
                                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay)
                                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                    df_ot.at[idx, '狀態'] = '已執行'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=df_ot); st.cache_data.clear(); st.rerun()

            with tabs[2]:
                st.subheader("👤 員工主表維護")
                e_ed = st.data_editor(df_emp, num_rows="dynamic", key="b_main")
                if st.button("💾 更新主表"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=e_ed); st.cache_data.clear(); st.success("OK")
            with tabs[3]: st.subheader("🏥 勞健保歷史明細"); st.dataframe(df_ins, use_container_width=True)
            with tabs[4]: st.subheader("🔑 系統帳號維護"); st.dataframe(df_acc, use_container_width=True)

if __name__ == "__main__":
    main()
