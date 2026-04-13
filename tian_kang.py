import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 雲端分頁定義 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET, EMP_SHEET, INS_SHEET = "salary_data", "emp_info", "ins_info"
ACC_SHEET, LOCK_SHEET = "user_accounts", "lock_status"
LEAVE_SHEET, OT_SHEET = "leave_requests", "ot_requests"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心邏輯：勞基法假別規則 ---
LEAVE_TYPES = {
    "特休": {"pay_ratio": 0.0, "deduct_balance": "剩餘特休時數", "desc": "全薪，扣特休"},
    "補休": {"pay_ratio": 0.0, "deduct_balance": "補休餘額", "desc": "全薪，扣補休"},
    "病假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "一年30天半薪"},
    "生理假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "每月1天半薪"},
    "事假(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "無薪"},
    "家庭照顧假(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "無薪"},
    "婚假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "8天全薪"},
    "喪假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "3-8天全薪"},
    "產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend", "deduct_balance": None, "desc": "8週"},
    "產檢假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7天全薪"},
    "陪產檢及陪產假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7天全薪"},
    "育嬰留職停薪(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "滿半年可申請"}
}

# --- 3. 工具函數 ---
def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()
def clean_val(v):
    try: return float(v) if v and str(v).strip() != "" else 0.0
    except: return 0.0

def get_seniority(start_date_str):
    try:
        start_date = datetime.strptime(str(start_date_str), "%Y-%m-%d")
        delta = datetime.now() - start_date
        return max(0, delta.days / 365.25)
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
        "月份": "月份", "生效月份": "生效月份", "姓名": "姓名", "身分證": "身分證",
        "勞保": "勞保", "健保": "健保", "健保人數": "健保人數", "電子郵件": "電子郵件",
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期", "補休餘額": "補休餘額",
        "剩餘特休時數": "剩餘特休時數", "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計", 
        "加班時薪": "加班時薪", "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "狀態": "狀態"
    }
    new_mapping = {c: mapping[k] for c in df.columns for k in mapping if k in c}
    df = df.rename(columns=new_mapping)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

# 💡 網銀格式保全：轉帳存入
def generate_bank_csv(df_source, df_employee, target_m):
    emp_sub = df_employee[['姓名', '身分證', '收款帳號']].drop_duplicates('姓名')
    f_df = df_source.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"], "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

# 📧 Email 發送保全 (承瑋大助專用)
def send_salary_email(to_email, name, month, unit, details_dict):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康管理部 <{S_EMAIL}>"; msg["To"] = to_email
    msg["Subject"] = f"【薪資通知】{month} 月份薪資明細 - {name}"
    rows = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    html = f"<html><body style='font-family:sans-serif;'><h2>👋 {name} 您好：</h2><p>這是您 {month} 的薪資明細：</p><table style='border-collapse:collapse; width:100%; max-width:450px;'>{rows}</table></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg)
        return True, "成功"
    except Exception as e: return False, str(e)

# --- 4. 主程式 ---
def main():
    st.title("🚀 天康薪資差勤一體化管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))
    INS_COLS = ['生效月份', '姓名', '身分證', '勞保', '健保', '健保人數', '勞健保個人負擔', '加保日期']

    # --- 讀取所有數據 ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=0), expected_cols=['姓名','單位','加班時薪','補休餘額','剩餘特休時數','電子郵件'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=0))
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=0), expected_cols=INS_COLS)
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=0))
        df_lv = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=0))
        df_ot = robust_clean(conn.read(worksheet=OT_SHEET, ttl=0))
        try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=0))
        except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
    except Exception as e: st.error(f"連線失敗: {e}"); st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["管理端登入", "員工查詢與申請", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("帳號"); pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): 
                        sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
        elif mode == "員工查詢與申請":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 【員工專區：薪資+差勤】 ---
    if role == 5:
        name = st.session_state.user_name.replace(" ", "")
        p_ins = df_ins[df_ins['姓名'] == name]
        s_date = p_ins.sort_values('加保日期').iloc[0]['加保日期'] if not p_ins.empty else "N/A"
        yrs = get_seniority(s_date)
        e_info = df_emp[df_emp['姓名'] == name].iloc[0]

        st.subheader(f"👋 {name} 同仁，歡迎使用管理系統")
        st.sidebar.info(f"🎖️ 年資：{yrs:.2f} 年\n🗓️ 加保日：{s_date}\n🎁 法定特休：{get_labor_law_special_leave(yrs)} 天")

        tab_e = st.tabs(["💰 薪資單查詢", "📅 請假與加班申請", "🔍 差勤紀錄"])
        
        with tab_e[0]:
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            ins_rows = []
            for m in p_pay['月份'].astype(str):
                v_ins = df_ins[(df_ins['姓名'] == name) & (df_ins['生效月份'].astype(str) <= m)]
                ins_rows.append(v_ins.sort_values('生效月份', ascending=False).iloc[0][['勞保','健保','健保人數','勞健保個人負擔']] if not v_ins.empty else pd.Series([0,0,0,0], index=['勞保','健保','健保人數','勞健保個人負擔']))
            p_pay = pd.concat([p_pay.reset_index(drop=True), pd.DataFrame(ins_rows).reset_index(drop=True)], axis=1)
            for c in ALL_VAR_COLS + ['勞保','健保','勞健保個人負擔']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
            b_cols = PHARMACY_VAR if str(e_info['單位']).strip() == "藥局" else CASE_MGR_VAR
            p_pay['實領總額'] = (clean_val(e_info['基本薪資合計']) + p_pay[b_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
            st.dataframe(p_pay[['月份', '姓名'] + b_cols + ['勞保', '健保', '勞健保個人負擔', '實領總額', '備註']])

        with tab_e[1]:
            c1, c2 = st.columns(2)
            with c1:
                st.metric("剩餘特休(小時)", f"{clean_val(e_info['剩餘特休時數'])} hr")
                st.metric("補休餘額(小時)", f"{clean_val(e_info['補休餘額'])} hr")
                with st.form("l_req"):
                    st.markdown("### 🌿 請假申請")
                    lt = st.selectbox("假別", list(LEAVE_TYPES.keys()))
                    ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 8.0, 1.0, 0.5), st.text_area("理由")
                    if st.form_submit_button("送出請假"):
                        conn.update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True)); st.success("已送審")
            with c2:
                with st.form("o_req"):
                    st.markdown("### ⚡ 加班提前預約")
                    od, oh = st.date_input("加班日期"), st.number_input("預計小時", 0.5, 12.0, 1.0, 0.5)
                    om = st.radio("處理方式", ["換錢", "換補休"])
                    orsn = st.text_area("加班原因")
                    if st.form_submit_button("預約加班"):
                        conn.update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(od)],"姓名":[name],"時數":[oh],"處理方式":[om],"原因":[orsn],"狀態":["待審核"]})], ignore_index=True)); st.success("預約成功")

        with tab_e[2]:
            st.write("🌿 請假紀錄"); st.dataframe(df_lv[df_lv['姓名']==name])
            st.write("⚡ 加班紀錄"); st.dataframe(df_ot[df_ot['姓名']==name])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    # --- 【管理端：老闆/會計/店長】 ---
    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()
        
        if role == 4: # 會計 (保全 8 欄位 + 排序修正)
            t_ac = st.tabs(["🏥 勞健保", "👤 員工清單"])
            with t_ac[0]:
                e_in = st.data_editor(df_ins[INS_COLS], num_rows="dynamic", key="ac_ed")
                if st.button("💾 更新勞健保"): conn.update(worksheet=INS_SHEET, data=e_in); st.cache_data.clear(); st.success("OK")
            with t_ac[1]:
                df_v = df_emp[["店別", "姓名", "單位", "身分證", "電子郵件"]].copy(); df_v['店別'] = df_v['店別'].astype(str)
                st.dataframe(df_v.sort_values("店別"))

        else: # 老闆 與 店長
            t_list = ["💰 薪資發薪", "📑 申請單審核", "👤 員工主表", "🏥 勞保記錄", "🔑 帳號管理"] if role == 1 else ["💰 薪資發薪"]
            tabs = st.tabs(t_list)

            with tabs[0]: # 薪資作業 (保全鎖定 + 店長時薪保密)
                all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique() if str(m).strip() != ""], reverse=True)
                target_m = st.sidebar.selectbox("月份", all_m if all_m else ["無"])
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
                
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份鎖定管理"):
                        if st.button("🔒 鎖定/🔓 解鎖本月"):
                            new_s = "OPEN" if is_locked else "LOCKED"
                            others = df_lock[df_lock['月份'].astype(str) != target_m]
                            conn.update(worksheet=LOCK_SHEET, data=pd.concat([others, pd.DataFrame({"月份":[target_m],"狀態":[new_s]})], ignore_index=True)); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
                
                if role == 1: # 老闆看到錢
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','電子郵件','加班時薪']], on='姓名', how='left')
                    edited = st.data_editor(curr, key="boss_pay")
                else: # 💡 店長看到時數 (邏輯保全：時薪絕對保密)
                    mgr_v = curr.merge(df_emp[['姓名','單位']], on='姓名', how='left')
                    disp_l = []
                    for _, r in mgr_v.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == r['姓名']].iloc[0].get('加班時薪', 0))
                        r['加班時數'] = round(clean_val(r['加班津貼']) / rate, 2) if rate > 0 else 0.0
                        disp_l.append(r)
                    final_mgr = pd.DataFrame(disp_l)
                    b_cols = PHARMACY_VAR if (not final_mgr.empty and "藥局" in str(final_mgr.iloc[0]['單位'])) else CASE_MGR_VAR
                    edited = st.data_editor(final_mgr[["月份","店別","姓名"] + [c for c in b_cols if c != "加班津貼"] + ["加班時數","備註"]], key="mgr_pay", disabled=is_locked)

                if not (is_locked and role == 3) and st.button("💾 同步薪資存檔"):
                    for idx, row in edited.iterrows():
                        emp_name = row['姓名']
                        if role == 3: # 店長存檔：後台自動乘回時薪
                            rate = clean_val(df_emp[df_emp['姓名'] == emp_name].iloc[0].get('加班時薪', 0))
                            df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == emp_name), '加班津貼'] = round(clean_val(row['加班時數']) * rate)
                        else: # 老闆直接存金額
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註":
                                    df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == emp_name), col] = row[col]
                    conn.update(worksheet=PAY_SHEET, data=df_pay); st.success("存檔成功")

                if role == 1: # 📧 老闆 Email & 網銀功能
                    c1, c2, c3 = st.columns(3)
                    with c1: st.download_button("📥 藥局網銀", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp, target_m), f"Phar_{target_m}.csv")
                    with c2: st.download_button("📥 個管師網銀", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp, target_m), f"Case_{target_m}.csv")
                    with c3:
                        if st.button("📧 批量寄送 Email"):
                            sc = 0
                            for _, r in edited.iterrows():
                                if pd.isna(r['電子郵件']) or "@" not in str(r['電子郵件']): continue
                                ok, _ = send_salary_email(r['電子郵件'], r['姓名'], target_m, r['單位'], {"應付總額": r['應付金額'], "備註": r['備註']})
                                if ok: sc += 1
                            st.success(f"✅ 成功寄出 {sc} 封。")

            if role == 1:
                with tabs[1]: # 🆕 審核案件 (增量功能)
                    st.subheader("📑 待核准清單")
                    c1, c2 = st.columns(2)
                    with c1: # 請假審核
                        p_l = df_lv[df_lv['狀態'] == '待審核']
                        for idx, row in p_l.iterrows():
                            with st.expander(f"🌿 {row['姓名']} - {row['類別']} ({row['時數']}hr)"):
                                p_ins = df_ins[df_ins['姓名'] == row['姓名']]
                                s_date = p_ins.sort_values('加保日期').iloc[0]['加保日期'] if not p_ins.empty else "N/A"
                                st.write(f"到職日：{s_date} | 原因：{row['事由']}")
                                if st.button("✅ 同意", key=f"la_{idx}"):
                                    rule = LEAVE_TYPES.get(row['類別'], {"pay_ratio":0.0})
                                    if rule.get('deduct_balance'):
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                        conn.update(worksheet=EMP_SHEET, data=df_emp)
                                    df_lv.at[idx, '狀態'] = '已核准'; conn.update(worksheet=LEAVE_SHEET, data=df_lv); st.rerun()
                    with c2: # 加班審核
                        p_o = df_ot[df_ot['狀態'] == '待審核']
                        for idx, row in p_o.iterrows():
                            with st.expander(f"⚡ {row['姓名']} - 加班 ({row['時數']}hr -> {row['處理方式']})"):
                                st.write(f"原因：{row['原因']}")
                                if st.button("✅ 核准加班", key=f"oa_{idx}"):
                                    df_ot.at[idx, '狀態'] = '已執行'
                                    if row['處理方式'] == '換錢':
                                        rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                                        df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), '加班津貼'] += round(rate * clean_val(row['時數']))
                                        conn.update(worksheet=PAY_SHEET, data=df_pay)
                                    else:
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                                        conn.update(worksheet=EMP_SHEET, data=df_emp)
                                    conn.update(worksheet=OT_SHEET, data=df_ot); st.rerun()
                with tabs[2]: # 👤 員工主表 (管理時薪/時數)
                    e_edited = st.data_editor(df_emp, num_rows="dynamic", key="boss_emp_main")
                    if st.button("💾 更新資料庫"): conn.update(worksheet=EMP_SHEET, data=e_edited); st.success("同步完成")

if __name__ == "__main__":
    main()
