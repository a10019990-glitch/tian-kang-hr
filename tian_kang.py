import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 系統設定與雲端分頁 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET, EMP_SHEET, INS_SHEET = "salary_data", "emp_info", "ins_info"
ACC_SHEET, LOCK_SHEET = "user_accounts", "lock_status"
LEAVE_SHEET, OT_SHEET = "leave_requests", "ot_requests"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 核心邏輯：勞基法規則 (全功能保全) ---
LEAVE_TYPES = {
    "特休": {"pay_ratio": 0.0, "deduct_balance": "剩餘特休時數", "desc": "全薪，扣特休"},
    "補休": {"pay_ratio": 0.0, "deduct_balance": "補休餘額", "desc": "全薪，扣補休"},
    "病假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "一年30天內半薪"},
    "生理假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "每月1天，半薪"},
    "事假(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "無薪"},
    "家庭照顧假(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "無薪"},
    "婚假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "8天全薪"},
    "喪假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "依親等3-8天全薪"},
    "產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend", "deduct_balance": None, "desc": "8週"},
    "流產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend", "deduct_balance": None, "desc": "依週數給假"},
    "產檢假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7天全薪"},
    "陪產檢及陪產假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7天全薪"},
    "產前假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "6天全薪"},
    "育嬰留職停薪(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "滿半年可申請"}
}

# --- 3. 工具函數 ---
def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()
def clean_val(v):
    try: return float(v) if v and str(v).strip() != "" else 0.0
    except: return 0.0

def get_seniority(start_date_str):
    if not start_date_str or start_date_str == "N/A": return 0
    try:
        start_date = pd.to_datetime(start_date_str)
        delta = datetime.now() - start_date
        return max(0, delta.days / 365.25)
    except: return 0

def get_labor_law_special_leave(years):
    if years < 0.5: return 0
    elif years < 1: return 7
    elif years < 2: return 10
    elif years < 3: return 14
    else: return min(30, 15 + int(years - 2))

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
        for key, val in mapping.items():
            if key == c or key in c:
                new_cols[c] = val; break
    df = df.rename(columns=new_cols)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    if expected_cols:
        for ec in expected_cols:
            if ec not in df.columns: df[ec] = 0 if any(x in ec for x in ["時", "額", "金", "負擔"]) else ""
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

def send_salary_email(to_email, name, month, unit, details_dict):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康管理部 <{S_EMAIL}>"; msg["To"] = to_email
    msg["Subject"] = f"【薪資通知】{month} 薪資明細 - {name}"
    rows = "".join([f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v} 元</td></tr>" if isinstance(v, (int, float)) else f"<tr><th style='border:1px solid #ddd; padding:10px; background:#f9f9f9; text-align:left;'>{k}</th><td style='border:1px solid #ddd; padding:10px; text-align:right;'>{v}</td></tr>" for k, v in details_dict.items()])
    html = f"<html><body><h3>👋 {name} 同仁您好：</h3><p>這是您 {month} 的薪資明細：</p><table style='border-collapse:collapse; width:100%; max-width:450px;'>{rows}</table></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg)
        return True
    except: return False

# --- 4. 數據讀取與智慧快取 (解決流量報錯) ---
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
    st.title("🚀 天康薪資差勤一體化管理系統")
    
    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear(); st.rerun()

    try:
        df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock = fetch_all_data()
    except Exception as e:
        st.error(f"連線失敗: {e}"); st.stop()

    PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金', '加班津貼']
    CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金', '加班津貼']
    ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR))

    if 'auth' not in st.session_state:
        mode = st.radio("入口", ["管理端登入", "員工專區", "新帳號註冊"], horizontal=True)
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
        elif mode == "員工專區":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("查詢登入"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        elif mode == "新帳號註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("註冊"):
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=ACC_SHEET, data=pd.concat([df_acc, pd.DataFrame({"姓名":[n.replace(" ","")], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})], ignore_index=True))
                    st.cache_data.clear(); st.success("OK")
        return

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 員工視角 (薪資查詢 + 差勤申請) ---
    if role == 5:
        name = st.session_state.user_name.replace(" ", "")
        p_ins_rec = df_ins[df_ins['姓名'] == name]
        s_date = str(p_ins_rec.sort_values('加保日期').iloc[0]['加保日期']) if not p_ins_rec.empty and '加保日期' in p_ins_rec.columns else "N/A"
        yrs = get_seniority(s_date); e_info = df_emp[df_emp['姓名'] == name].iloc[0] if not df_emp[df_emp['姓名'] == name].empty else {}
        st.subheader(f"👋 {name} 同仁，歡迎使用管理系統")
        st.sidebar.info(f"🎖️ 年資：{yrs:.2f} 年\n🗓️ 加保日：{s_date}\n🎁 法定特休：{get_labor_law_special_leave(yrs)} 天")

        tab_e = st.tabs(["💰 薪資單查詢", "📅 請假與加班申請", "🔍 差勤紀錄"])
        with tab_e[0]:
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            if '月份' in p_pay.columns:
                ins_rows = []
                for m in p_pay['月份'].astype(str):
                    v_ins = df_ins[(df_ins['姓名'] == name) & (df_ins['生效月份'].astype(str) <= m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                    ins_rows.append(v_ins.sort_values('生效月份', ascending=False).iloc[0].reindex(['勞保','健保','勞健保個人負擔'], fill_value=0) if not v_ins.empty else pd.Series([0,0,0], index=['勞保','健保','勞健保個人負擔']))
                p_pay = pd.concat([p_pay.reset_index(drop=True), pd.DataFrame(ins_rows).reset_index(drop=True)], axis=1)
                for c in ALL_VAR_COLS + ['勞保','健保','勞健保個人負擔']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
                b_cols = PHARMACY_VAR if (e_info.get('單位') == "藥局") else CASE_MGR_VAR
                p_pay['實領總額'] = (clean_val(e_info.get('基本薪資合計',0)) + clean_val(e_info.get('執照津貼',0)) + clean_val(e_info.get('車資補貼',0)) + p_pay[b_cols].sum(axis=1)) - p_pay['勞健保個人負擔']
                st.dataframe(p_pay[['月份', '姓名'] + b_cols + ['勞保', '健保', '勞健保個人負擔', '實領總額', '備註']])
        
        with tab_e[1]:
            c1, c2 = st.columns(2)
            with c1:
                st.metric("補休餘額", f"{clean_val(e_info.get('補休餘額',0))} hr")
                with st.form("l_req"):
                    lt = st.selectbox("假別", list(LEAVE_TYPES.keys())); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 8.0, 1.0, 0.5), st.text_area("理由")
                    if st.form_submit_button("送出請假"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True))
                        st.cache_data.clear(); st.success("已送審")
            with c2:
                with st.form("o_req"):
                    st.markdown("### ⚡ 加班預約"); od, oh, om = st.date_input("日期"), st.number_input("小時", 0.5, 12.0, 1.0, 0.5), st.radio("處理", ["換錢", "換補休"])
                    if st.form_submit_button("預約加班"):
                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(od)],"姓名":[name],"時數":[oh],"處理方式":[om],"原因":["提前預約"],"狀態":["待審核"]})], ignore_index=True))
                        st.cache_data.clear(); st.success("已預約")
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    # --- 管理端 ---
    else:
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()
        
        if role == 4: # 會計 (保全 8 欄位 + 排序)
            t_ac = st.tabs(["🏥 勞健保維護", "👤 員工名單"])
            with t_ac[0]:
                e_in = st.data_editor(df_ins, num_rows="dynamic", key="ac_ed")
                if st.button("💾 更新資料"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=INS_SHEET, data=e_in); st.cache_data.clear(); st.success("OK")
            with t_ac[1]: st.dataframe(df_emp[["店別", "姓名", "單位", "身分證", "電子郵件"]].copy().sort_values("店別"))

        else: # 老闆 與 店長
            t_list = ["💰 薪資發薪作業", "📑 申請單審核中心", "👤 員工資料庫", "🏥 勞健保明細", "🔑 帳號管理"] if role == 1 else ["💰 薪資發薪作業"]
            tabs = st.tabs(t_list)

            with tabs[0]: # 薪資作業
                all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if '月份' in df_pay.columns else ["無"]
                target_m = st.sidebar.selectbox("月份切換", all_m, key="m_box")
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
                
                # 💡 月份管理復原 (新增/刪除月份) ✅
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理 (新增/刪除/鎖定)"):
                        new_m_in = st.text_input("建立新月份", "2026-06")
                        if st.button("🚀 執行建立"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            new_r = pd.DataFrame({"月份":[new_m_in]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS: new_r[c] = 0
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/🔓 解鎖"):
                            new_s = "OPEN" if is_locked else "LOCKED"; others = df_lock[df_lock['月份'].astype(str) != target_m]
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=LOCK_SHEET, data=pd.concat([others, pd.DataFrame({"月份":[target_m],"狀態":[new_s]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        del_m_in = st.selectbox("刪除月份", all_m, key="del_box")
                        if st.button("🔥 刪除月份") and st.checkbox(f"確認刪除 {del_m_in}"):
                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m_in]); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                if role == 3: curr = curr[curr['姓名'].isin(df_emp[df_emp['店別'].astype(str).str.zfill(2) == shop]['姓名'])]
                
                if role == 1: # 老闆視角：看錢 + 應付金額
                    curr = curr.merge(df_emp[['姓名','單位','基本薪資合計','執照津貼','車資補貼','電子郵件','加班時薪']], on='姓名', how='left')
                    l_ins_list = []
                    for n in curr['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名', '勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n, 0], index=['姓名', '勞健保個人負擔']))
                    curr = curr.merge(pd.DataFrame(l_ins_list), on='姓名', how='left')
                    for c in ALL_VAR_COLS + ['基本薪資合計','執照津貼','車資補貼','勞健保個人負擔']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                    edited = st.data_editor(curr, key="boss_main_pay")
                else: # 💡 店長視角 (時薪絕對保密：改填時數)
                    mgr_v = curr.merge(df_emp[['姓名','單位']], on='姓名', how='left')
                    disp_l = []
                    for _, r in mgr_v.iterrows():
                        rate = clean_val(df_emp[df_emp['姓名'] == r['姓名']].iloc[0].get('加班時薪', 0))
                        r['加班時數'] = round(clean_val(r['加班津貼']) / rate, 2) if rate > 0 else 0.0; disp_l.append(r)
                    final_mgr = pd.DataFrame(disp_l); b_cols = PHARMACY_VAR if (not final_mgr.empty and final_mgr.iloc[0].get('單位') == "藥局") else CASE_MGR_VAR
                    edited = st.data_editor(final_mgr[["月份","店別","姓名"] + [c for c in b_cols if c != "加班津貼"] + ["加班時數","備註"]], disabled=is_locked)

                if not (is_locked and role == 3) and st.button("💾 同步存檔"):
                    for idx, row in edited.iterrows():
                        if role == 3:
                            rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                            df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), '加班津貼'] = round(clean_val(row['加班時數']) * rate)
                        else:
                            for col in edited.columns:
                                if col in ALL_VAR_COLS or col == "備註": df_pay.loc[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), col] = row[col]
                    st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay); st.cache_data.clear(); st.success("OK")

                if role == 1: # 網銀 CSV 與 Email 保全 ✅
                    c1, c2, c3 = st.columns(3)
                    with c1: st.download_button("📥 藥局網銀", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp, target_m), f"Phar_{target_m}.csv")
                    with c2: st.download_button("📥 個管師網銀", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp, target_m), f"Case_{target_m}.csv")
                    with c3:
                        if st.button("📧 批量發送 Email"):
                            for _, r in edited.iterrows():
                                if not pd.isna(r['電子郵件']): send_salary_email(r['電子郵件'], r['姓名'], target_m, r['單位'], {"實領總額": r.get('應付金額', 0), "備註": r.get('備註','')})
                            st.success("✅ 完成")

            if role == 1: # Boss 專屬分頁
                with tabs[1]: # 💡 修復 ValueError：防彈計薪邏輯
                    st.subheader("📑 待核准申請")
                    c1, c2 = st.columns(2)
                    with c1:
                        p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                        for idx, row in p_l.iterrows():
                            with st.expander(f"{row.get('姓名','')} - {row.get('類別','')}"):
                                if st.button("✅ 核准請假", key=f"la_{idx}"):
                                    rule = LEAVE_TYPES.get(row['類別'], {})
                                    if rule.get('deduct_balance') and rule['deduct_balance'] in df_emp.columns:
                                        df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                    df_lv.at[idx, '狀態'] = '已核准'; st.connection("gsheets", type=GSheetsConnection).update(worksheet=LEAVE_SHEET, data=df_lv); st.cache_data.clear(); st.rerun()
                    with c2:
                        p_o = df_ot[df_ot['狀態'] == '待審核'] if '狀態' in df_ot.columns else pd.DataFrame()
                        for idx, row in p_o.iterrows():
                            with st.expander(f"{row.get('姓名','')} - 加班"):
                                if st.button("✅ 同意加班", key=f"oa_{idx}"):
                                    rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                                    money = round(rate * clean_val(row.get('時數', 0)))
                                    # 💡 鋼鐵防護：先定位索引，確保不噴 ValueError
                                    target_idx = df_pay.index[(df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名'])]
                                    if not target_idx.empty:
                                        if row.get('處理方式','') == '換錢':
                                            df_pay.at[target_idx[0], '加班津貼'] = clean_val(df_pay.at[target_idx[0], '加班津貼']) + money
                                        else:
                                            df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                                            st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=df_emp)
                                        df_ot.at[idx, '狀態'] = '已執行'
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=PAY_SHEET, data=df_pay)
                                        st.connection("gsheets", type=GSheetsConnection).update(worksheet=OT_SHEET, data=df_ot); st.cache_data.clear(); st.rerun()
                                    else: st.error("發薪表中找不到該員工，無法加錢。")
                with tabs[2]:
                    e_ed = st.data_editor(df_emp, num_rows="dynamic", key="b_main")
                    if st.button("💾 更新員工資料庫"): st.connection("gsheets", type=GSheetsConnection).update(worksheet=EMP_SHEET, data=e_ed); st.cache_data.clear(); st.success("OK")
                with tabs[3]: st.subheader("🏥 勞健保紀錄"); st.dataframe(df_ins)
                with tabs[4]: st.subheader("🔑 帳號管理"); st.dataframe(df_acc)

if __name__ == "__main__":
    main()
