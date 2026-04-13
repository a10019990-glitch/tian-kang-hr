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

# --- 2. 勞基法假別定義 ---
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
        new_cols = {}
        for c in df.columns:
            for k, v in mapping_dict.items():
                if k == c or k in c:
                    new_cols[c] = v; break
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
    rows = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v} 元</td></tr>" if isinstance(v, (int, float)) else f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    html = f"<html><body><h3>👋 {name} 同仁您好：</h3><p>這是您 {month} 的薪資明細：</p><table style='border-collapse:collapse; width:100%; max-width:450px;'>{rows}</table></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg); return True
    except: return False

# --- 4. 數據讀取與智慧快取 ---
@st.cache_data(ttl=60)
def fetch_all_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    std_map = {
        "月份": "月份", "姓名": "姓名", "身分證": "身分證", "加保日期": "加保日期",
        "補休餘額": "補休餘額", "剩餘特休時數": "剩餘特休時數", "加班時薪": "加班時薪", "基本薪資合計": "基本薪資合計"
    }
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
    st.title("🚀 天康薪資差勤一體化管理系統")
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
            if st.button("登入系統"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): 
                        sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
        elif mode == "員工查詢":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("查詢資料"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 5. 員工專區 ---
    if role == 5:
        name = st.session_state.user_name.replace(" ", "")
        p_ins = df_ins[df_ins['姓名'] == name]
        s_date = str(p_ins.sort_values('加保日期').iloc[0]['加保日期']) if not p_ins.empty and '加保日期' in p_ins.columns else "N/A"
        e_info = df_emp[df_emp['姓名'] == name].iloc[0] if not df_emp[df_emp['姓名'] == name].empty else {}
        st.subheader(f"👋 {name} 同仁")
        st.sidebar.info(f"入職日：{s_date}")

        t1, t2, t3 = st.tabs(["💰 薪資單", "📅 申請假單與加班", "🔍 紀錄查詢"])
        with t1:
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            if not p_pay.empty:
                st.dataframe(p_pay)
            else: st.warning("查無發薪紀錄")
        with t2:
            st.metric("補休餘額", f"{clean_val(e_info.get('補休餘額',0))} hr")
            with st.form("l_f"):
                lt = st.selectbox("假別/項目", list(LEAVE_TYPES.keys()) + ["加班預約"]); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 12.0, 1.0, 0.5), st.text_area("理由")
                if st.form_submit_button("送出申請"):
                    if lt == "加班預約": st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["累積補休"],"原因":[lr],"狀態":["待審核"]})], ignore_index=True))
                    else: st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True))
                    st.cache_data.clear(); st.success("申請成功")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

    # --- 6. 管理端 ---
    else:
        if st.sidebar.button("安全登出"): del st.session_state['auth']; st.rerun()
        
        if role == 4: # 會計
            e_in = st.data_editor(df_ins, num_rows="dynamic")
            if st.button("💾 更新資料"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=INS_SHEET, data=e_in); st.cache_data.clear(); st.success("OK")

        else: # 老闆 與 店長
            tabs = st.tabs(["💰 薪資發薪作業", "📑 申請單審核中心", "👤 員工主資料維護", "🏥 勞健保紀錄", "🔑 帳號維護"])
            
            with tabs[0]: # 薪資作業 (保全鎖定與店長隔離)
                all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if '月份' in df_pay.columns else ["無"]
                target_m = st.sidebar.selectbox("月份", all_m, key="m_box")
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
                
                # 💡 老冊管理復原 (新增/刪除) ✅
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理系統"):
                        new_m = st.text_input("新增月份", "2026-06")
                        if st.button("🚀 執行建立"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            new_r = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"] if "店別" in df_emp.columns else "01", "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/🔓 解鎖"):
                            new_s = "OPEN" if is_locked else "LOCKED"; others = df_lock[df_lock['月份'].astype(str) != target_m]
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=LOCK_SHEET, data=pd.concat([others, pd.DataFrame({"月份":[target_m],"狀態":[new_s]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        del_m = st.selectbox("選取刪除月份", all_m, key="del_box")
                        if st.button("🔥 執行刪除") and st.checkbox(f"我確認刪除 {del_m}"):
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m]); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
                
                if role == 1: # 老闆視角：保全時薪
                    curr = curr.merge(df_emp[['姓名','基本薪資合計','執照津貼','車資補貼','電子郵件','加班時薪']], on='姓名', how='left')
                    l_ins_list = []
                    for n in curr['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名','勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n,0], index=['姓名','勞健保個人負擔']))
                    curr = curr.merge(pd.DataFrame(l_ins_list), on='姓名', how='left')
                    for c in ALL_VAR_COLS + ['基本薪資合計','勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + clean_val(curr.get('執照津貼',0)) + clean_val(curr.get('車資補貼',0)) + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                    edited = st.data_editor(curr, key="boss_pay_final")
                    if st.button("📧 批量寄送 Email"):
                        for _, r in edited.iterrows():
                            if not pd.isna(r.get('電子郵件')): send_salary_email(r['電子郵件'], r['姓名'], target_m, {"總額": r.get('應付金額', 0)})
                        st.success("✅ 完成")
                else: # 💡 店長視角 (隱私隔離 ✅)
                    mgr_view = curr.merge(df_emp[['姓名']], on='姓名', how='left')
                    disp_l = []
                    for _, r in mgr_view.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == r['姓名']].iloc[0].get('加班時薪', 0))
                        r['加班時數'] = round(clean_val(r['加班津貼']) / rate, 2) if rate > 0 else 0.0; disp_l.append(r)
                    final_mgr = pd.DataFrame(disp_l); edited = st.data_editor(final_mgr[["月份","姓名"] + [c for c in ALL_VAR_COLS if c != "加班津貼"] + ["加班時數","備註"]], disabled=is_locked)

                if st.button("💾 同步存檔") and not (is_locked and role == 3):
                    for idx, row in edited.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                        if role == 3: df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), '加班津貼'] = round(clean_val(row['加班時數']) * rate)
                        else:
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註": df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), col] = row[col]
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay); st.cache_data.clear(); st.success("OK")

            with tabs[1]: # 審核中心
                if role == 1:
                    c1, c2 = st.columns(2)
                    with c1: # 假單
                        p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                        for idx, row in p_l.iterrows():
                            with st.expander(f"🌿 {row.get('姓名')} - {row.get('類別')}"):
                                if st.button("✅ 核准", key=f"la_{idx}"):
                                    rule = LEAVE_TYPES.get(row['類別'], {})
                                    if rule.get('deduct_balance') in df_emp.columns:
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                    df_lv.at[idx, '狀態'] = '已核准'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=df_lv); st.cache_data.clear(); st.rerun()
                    with c2: # 加班
                        p_o = df_ot[df_ot['狀態'] == '待審核'] if '狀態' in df_ot.columns else pd.DataFrame()
                        for idx, row in p_o.iterrows():
                            with st.expander(f"⚡ {row.get('姓名')} - 加班"):
                                if st.button("✅ 同意", key=f"oa_{idx}"):
                                    df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                                    df_ot.at[idx, '狀態'] = '已核准'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=df_ot); st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.rerun()

            # 💡 核心修正點：Boss 看到最原始的完整資料 ✅
            with tabs[2]: # 員工主表
                st.subheader("👤 員工資料庫")
                e_ed = st.data_editor(df_emp, num_rows="dynamic", key="boss_main_ed")
                if st.button("💾 更新員工資料"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=e_ed); st.cache_data.clear(); st.success("OK")
            with tabs[3]: # 勞健保明細
                st.subheader("🏥 勞健保紀錄")
                st.dataframe(df_ins, use_container_width=True)
            with tabs[4]: # 帳號管理
                st.subheader("🔑 帳號維護")
                st.dataframe(df_acc, use_container_width=True)

if __name__ == "__main__":
    main()
