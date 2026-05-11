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

st.set_page_config(page_title="天康藥局管理系統", layout="wide")

# --- 2. 核心分類與假別定義 ---
PHARMACY_VAR = ['職務加給', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
CASE_MGR_VAR = ['電訪', '超額電訪', '家訪', '超額家訪', '三節獎金', '輔具獎金']
ALL_VAR_COLS = list(set(PHARMACY_VAR + CASE_MGR_VAR + ['加班津貼']))

LEAVE_TYPES = {
    "特休": {"deduct": "剩餘特休時數"}, "補休": {"deduct": "補休餘額"},
    "病假(半薪)": {"deduct": None}, "生理假(半薪)": {"deduct": None},
    "事假(無薪)": {"deduct": None}, "家庭照顧假(無薪)": {"deduct": None},
    "婚假(全薪)": {"deduct": None}, "喪假(全薪)": {"deduct": None},
    "產假(全薪/半薪)": {"deduct": None}, "流產假": {"deduct": None},
    "產檢假(全薪)": {"deduct": None}, "陪產檢及陪產假(全薪)": {"deduct": None},
    "產前假(全薪)": {"deduct": None}, "育嬰留職停薪(無薪)": {"deduct": None}
}

# --- 3. 工具函數 ---
def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()

def clean_val(v):
    try:
        if pd.isna(v) or str(v).strip() == "": return 0.0
        return float(str(v).replace(',', '').replace('$', ''))
    except: return 0.0

def robust_clean(df, mapping_dict=None, expected_cols=None):
    if df is None or df.empty: 
        return pd.DataFrame(columns=expected_cols if expected_cols else [])
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    if mapping_dict:
        new_cols = {c: mapping_dict[k] for c in df.columns for k in mapping_dict if k in c}
        df = df.rename(columns=new_cols)
    if expected_cols:
        for c in expected_cols:
            if c not in df.columns: df[c] = 0.0 if "時數" in c or "津貼" in c else ""
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

def get_annual_leave_hours(start_date_str):
    if not start_date_str or pd.isna(start_date_str) or str(start_date_str).strip() == "": return 0.0
    try:
        sd = pd.to_datetime(start_date_str); now = pd.to_datetime(datetime.now().date())
        y = (now - sd).days / 365.25
        if y < 0.5: return 0.0
        elif y < 1: return 24.0
        elif y < 2: return 56.0
        elif y < 3: return 80.0
        elif y < 5: return 112.0
        elif y < 10: return 120.0
        else: return min(15 + (int(y) - 9), 30) * 8.0
    except: return 0.0

def generate_bank_csv(df_source, df_employee):
    cols_to_add = ['身分證', '收款帳號']
    df_clean = df_source.drop(columns=[c for c in cols_to_add if c in df_source.columns], errors='ignore')
    emp_sub = df_employee[['姓名'] + [c for c in cols_to_add if c in df_employee.columns]].drop_duplicates('姓名')
    f_df = df_clean.merge(emp_sub, on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df.get("身分證",""), "收款帳號": f_df.get("收款帳號",""),
        "交易金額": f_df.get("應付金額", 0), "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def send_salary_email(to_email, name, month, details_dict):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康藥局管理部 <{S_EMAIL}>"; msg["To"] = str(to_email)
    msg["Subject"] = f"【薪資明細通知】{month} 月份 - {name}"

    rows_html = ""
    for k, v in details_dict.items():
        color = "#333" if clean_val(v) != 0 else "#999"
        rows_html += f"""<tr>
            <td style="border: 1px solid #ddd; padding: 8px; background-color: #f9f9f9; font-weight: bold;">{k}</td>
            <td style="border: 1px solid #ddd; padding: 8px; text-align: right; color: {color};">{v}</td>
        </tr>"""

    html_content = f"""
    <html><body style="font-family: Arial, sans-serif;">
        <h2 style="color: #2c3e50;">👋 {name} 同仁您好：</h2>
        <p>以下是您於 <strong>{month}</strong> 月份的薪資結算明細：</p>
        <table style="border-collapse: collapse; width: 100%; max-width: 500px; border: 1px solid #ddd;">
            <thead><tr style="background-color: #2c3e50; color: white;">
                <th style="padding: 12px; text-align: left;">薪資項目</th>
                <th style="padding: 12px; text-align: right;">金額/數值</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <p style="color: #7f8c8d; font-size: 12px; margin-top: 20px;">* 本信件為系統自動結算，如有疑問請洽店長或管理部。</p>
    </body></html>
    """
    msg.attach(MIMEText(html_content, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(S_EMAIL, S_PW); s.send_message(msg); return True
    except: return False

# --- 4. 數據讀取與防護 ---
@st.cache_data(ttl=120)
def fetch_all_data():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        std_map = {
            "月份": "月份", "姓名": "姓名", "身分證": "身分證", "加保日期": "加保日期",
            "補休餘額": "補休餘額", "剩餘特休時數": "剩餘特休時數", "累計應得特休": "累計應得特休",
            "加班時薪": "加班時薪", "單位": "單位", "店別": "店別", "生效月份": "生效月份",
            "本薪": "本薪", 
            "三節獎金(評估表現發放)": "績效獎金(評估表現發放)", # 兼容舊名稱
            "績效獎金(評估表現發放)": "績效獎金(評估表現發放)", # 正名
            "保障獎金": "保障獎金", "固定加班津貼": "固定加班津貼",
            "執照津貼": "執照津貼", "車資補貼": "車資補貼", 
            "電子郵件": "電子郵件", "收款帳號": "收款帳號"
        }
        std_cols = list(set(std_map.values()))
        
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=30), std_map, std_cols)
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=30), std_map, std_cols + ['本月加班時數', '換錢時數', '加班津貼'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=30), std_map, std_cols + ['勞健保個人負擔'])
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=30), None, ["帳號", "密碼", "姓名", "身分證"])
        df_lv = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=30), None, ["日期", "姓名", "類別", "時數", "狀態"])
        df_ot = robust_clean(conn.read(worksheet=OT_SHEET, ttl=30), None, ["日期", "姓名", "時數", "處理方式", "狀態"])
        try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=30), None, ["月份", "狀態"])
        except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
        
        # 強制轉為數值型態
        num_cols = ['本月加班時數', '換錢時數', '加班津貼', '補休餘額', '剩餘特休時數', '累計應得特休', '加班時薪', 
                    '本薪', '績效獎金(評估表現發放)', '保障獎金', '固定加班津貼', '執照津貼', '車資補貼']
        for col in num_cols:
            if col in df_pay.columns: df_pay[col] = pd.to_numeric(df_pay[col], errors='coerce').fillna(0.0)
            if col in df_emp.columns: df_emp[col] = pd.to_numeric(df_emp[col], errors='coerce').fillna(0.0)
        return df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock
    except Exception as e:
        if "429" in str(e): st.error("🚨 API 配額用盡，請稍候再重新載入。"); st.stop()
        else: raise e

def main():
    st.title("🚀 天康藥局管理系統")
    if st.sidebar.button("🔄 同步資料 (清除快取)"): st.cache_data.clear(); st.rerun()

    try:
        df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock = fetch_all_data()
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error("🚨 系統連線暫時受到限制。請稍候再試。"); st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["管理端登入", "員工查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("帳號"); pw = st.text_input("密碼", type="password")
            if st.button("登入管理"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop, st.session_state.mgr_type = 1, "ALL", "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop, st.session_state.mgr_type = 4, "ACCOUNTING", "ALL"
                    elif acc.startswith("mgr_"): 
                        sid = re.findall(r'\d+', acc)
                        shop_id = sid[0].zfill(2) if sid else "ALL"
                        st.session_state.auth, st.session_state.shop, st.session_state.mgr_type = 3, shop_id, "藥局"
                    elif acc.startswith("cmgr_"): 
                        sid = re.findall(r'\d+', acc)
                        shop_id = sid[0].zfill(2) if sid else "ALL"
                        st.session_state.auth, st.session_state.shop, st.session_state.mgr_type = 3, shop_id, "個管師"
                    st.rerun()
        elif mode == "員工查詢":
            e_acc = st.text_input("員工帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("登入查詢"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        
        elif mode == "新帳號註冊":
            st.subheader("📝 註冊員工專區帳號")
            with st.form("reg_form"):
                new_acc = st.text_input("設定登入帳號")
                st.caption("※ 藥局單店店長：`mgr_01` \n\n※ 個管師總區主管：`cmgr_all` \n\n※ 一般員工：建議英文+數字")
                new_pw = st.text_input("設定登入密碼", type="password")
                confirm_pw = st.text_input("確認密碼", type="password")
                new_name = st.text_input("真實姓名 (需與發薪表完全一致)")
                new_id = st.text_input("身分證字號")
                
                if st.form_submit_button("送出註冊"):
                    if not new_acc or not new_pw or not new_name or not new_id:
                        st.warning("⚠️ 所有欄位皆為必填！")
                    elif new_pw != confirm_pw:
                        st.warning("⚠️ 兩次輸入的密碼不一致！")
                    elif new_acc in df_acc['帳號'].values:
                        st.warning("⚠️ 此帳號已被使用，請更換一個。")
                    else:
                        new_user = pd.DataFrame({
                            "帳號": [new_acc],
                            "密碼": [hash_password(new_pw)],
                            "姓名": [new_name.replace(" ", "")],
                            "身分證": [new_id]
                        })
                        updated_acc = pd.concat([df_acc, new_user], ignore_index=True)
                        conn.update(worksheet=ACC_SHEET, data=updated_acc)
                        st.cache_data.clear()
                        st.success("✅ 註冊成功！請將畫面上方的「系統入口」切換至【員工查詢】或【管理端登入】。")
        return

    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # --- 員工專區 ---
        name = st.session_state.user_name.replace(" ", "")
        st.subheader(f"👋 {name} 同仁")
        t1, t2, t3 = st.tabs(["💰 薪資單", "📅 差勤申請", "🔍 歷史紀錄"])
        with t1: 
            p_pay = df_pay[df_pay['姓名'] == name].copy()
            e_info = df_emp[df_emp['姓名'] == name].iloc[0] if not df_emp[df_emp['姓名'] == name].empty else pd.Series()
            if not p_pay.empty and not e_info.empty:
                ins_list = []
                for m in p_pay['月份'].astype(str):
                    v_ins = df_ins[(df_ins['姓名'] == name) & (df_ins['生效月份'].astype(str) <= m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                    ins_list.append(v_ins.sort_values('生效月份', ascending=False).iloc[0].reindex(['勞健保個人負擔'], fill_value=0) if not v_ins.empty else pd.Series([0], index=['勞健保個人負擔']))
                p_pay = pd.concat([p_pay.reset_index(drop=True), pd.DataFrame(ins_list).reset_index(drop=True)], axis=1)
                b_cols = PHARMACY_VAR if e_info.get('單位') == "藥局" else CASE_MGR_VAR
                for c in ALL_VAR_COLS + ['勞健保個人負擔', '本月加班時數', '換錢時數']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
                
                p_pay['本薪'] = clean_val(e_info.get('本薪', 0))
                p_pay['績效獎金(評估表現發放)'] = clean_val(e_info.get('績效獎金(評估表現發放)', 0))
                p_pay['保障獎金'] = clean_val(e_info.get('保障獎金', 0))
                p_pay['固定加班津貼'] = clean_val(e_info.get('固定加班津貼', 0))
                p_pay['執照津貼'] = clean_val(e_info.get('執照津貼', 0))
                p_pay['車資補貼'] = clean_val(e_info.get('車資補貼', 0))
                
                p_pay['實領總額'] = (p_pay['本薪'] + p_pay['績效獎金(評估表現發放)'] + p_pay['保障獎金'] + p_pay['固定加班津貼'] + p_pay['執照津貼'] + p_pay['車資補貼'] + p_pay[b_cols].sum(axis=1) + p_pay['加班津貼']) - p_pay['勞健保個人負擔']
                
                display_df = p_pay[['月份', '本薪', '績效獎金(評估表現發放)', '保障獎金', '固定加班津貼', '執照津貼', '車資補貼', '加班津貼'] + b_cols + ['本月加班時數', '換錢時數', '勞健保個人負擔', '實領總額', '備註']].copy()
                display_df = display_df.rename(columns={'加班津貼': '加班費'})
                st.dataframe(display_df, use_container_width=True)
        with t2:
            ebal = df_emp[df_emp['姓名']==name].iloc[0] if not df_emp[df_emp['姓名']==name].empty else {}
            c1, c2 = st.columns(2)
            c1.metric("🎯 特休餘額", f"{clean_val(ebal.get('剩餘特休時數',0))} hr")
            c2.metric("⚡ 補休餘額", f"{clean_val(ebal.get('補休餘額',0))} hr")
            with st.form("emp_apply"):
                lt = st.selectbox("申請項目", list(LEAVE_TYPES.keys()) + ["加班預約", "補休轉現金"]); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 12.0, 1.0, 0.5), st.text_area("理由")
                if st.form_submit_button("送出"):
                    if "加班" in lt: conn.update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["累積補休"],"原因":[lr],"狀態":["待審核"]})], ignore_index=True))
                    elif "補休" in lt: conn.update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["換錢"],"原因":["補休核現"],"狀態":["待審核"]})], ignore_index=True))
                    else: conn.update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True))
                    st.cache_data.clear(); st.success("已提交")
        with t3: st.write("請假紀錄"); st.dataframe(df_lv[df_lv['姓名']==name]); st.write("加班紀錄"); st.dataframe(df_ot[df_ot['姓名']==name])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else: # --- 管理端 ---
        if st.sidebar.button("安全登出"): del st.session_state['auth']; st.rerun()
        if role == 3: t_titles = ["💰 薪資發薪作業"]
        elif role == 4: t_titles = ["🏥 勞健保紀錄維護"]
        else: t_titles = ["💰 薪資發薪作業", "📑 申請單審核中心", "👤 員工主資料維護", "🏥 勞健保紀錄維護", "🔑 帳號與權限管理"]
        tabs = st.tabs(t_titles)

        if "💰 薪資發薪作業" in t_titles:
            with tabs[0]:
                all_m = sorted([str(m) for m in df_pay['月份'].dropna().unique()], reverse=True) if '月份' in df_pay.columns else ["無"]
                target_m = st.sidebar.selectbox("切換月份", all_m, key="m_box")
                is_locked = any(df_lock[df_lock['月份'].astype(str) == target_m]['狀態'] == "LOCKED") if not df_lock.empty else False
                
                if role == 1:
                    with st.sidebar.expander("🛠️ 月份管理"):
                        new_m = st.text_input("新增 (YYYY-MM)", "2026-06")
                        if st.button("🚀 建立"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            new_r = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS + ['本月加班時數', '換錢時數']: new_r[c] = 0.0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/解鎖"):
                            conn.update(worksheet=LOCK_SHEET, data=pd.concat([df_lock[df_lock['月份'].astype(str) != target_m], pd.DataFrame({"月份":[target_m],"狀態":["OPEN" if is_locked else "LOCKED"]})], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        del_m = st.selectbox("刪除月份", all_m, key="del_box")
                        if st.button("🔥 執行刪除") and st.checkbox("確認"):
                            conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m]); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                
                if role == 1: # --- 老闆視角 ---
                    cols_from_emp = ['單位', '本薪', '績效獎金(評估表現發放)', '保障獎金', '固定加班津貼', '執照津貼', '車資補貼', '電子郵件', '加班時薪', '補休餘額', '剩餘特休時數', '店別']
                    curr = curr.drop(columns=[c for c in curr.columns if c in cols_from_emp], errors='ignore')
                    curr = curr.merge(df_emp[['姓名'] + [c for c in cols_from_emp if c in df_emp.columns]], on='姓名', how='left')
                    curr.rename(columns={'補休餘額': '現有補休', '剩餘特休時數': '現有特休'}, inplace=True)
                    
                    l_ins_list = []
                    for n in curr['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名','勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n,0], index=['姓名','勞健保個人負擔']))
                    curr = curr.merge(pd.DataFrame(l_ins_list), on='姓名', how='left')
                    
                    calc_cols = ALL_VAR_COLS + ['本薪', '績效獎金(評估表現發放)', '保障獎金', '固定加班津貼', '勞健保個人負擔', '本月加班時數', '換錢時數', '現有補休', '現有特休', '執照津貼', '車資補貼']
                    for c in calc_cols: 
                        if c not in curr.columns: curr[c] = 0.0
                        curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0.0)
                    
                    curr['應付金額'] = (curr['本薪'] + curr['績效獎金(評估表現發放)'] + curr['保障獎金'] + curr['固定加班津貼'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                    
                    curr = curr.rename(columns={'加班津貼': '加班費'})
                    
                    st.subheader("💊 藥局組")
                    base_show_cols = ['月份','店別','姓名','現有特休','現有補休','本月加班時數','換錢時數', '本薪', '績效獎金(評估表現發放)', '保障獎金', '固定加班津貼', '執照津貼', '車資補貼', '加班費', '勞健保個人負擔', '應付金額', '電子郵件']
                    ed_p = st.data_editor(curr[curr['單位'] == "藥局"][base_show_cols + PHARMACY_VAR + ['備註']], disabled=["現有特休", "現有補休", "勞健保個人負擔", "加班費"] if not is_locked else True, key="bp")
                    
                    st.subheader("📂 個管師組")
                    ed_c = st.data_editor(curr[curr['單位'] == "個管師"][base_show_cols + CASE_MGR_VAR + ['備註']], disabled=["現有特休", "現有補休", "勞健保個人負擔", "加班費"] if not is_locked else True, key="bc")
                    
                    if st.button("💾 老闆同步存檔") and not is_locked:
                        for _, r in pd.concat([ed_p, ed_c]).iterrows():
                            mask_p, mask_e = (df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == r['姓名']), df_emp['姓名'] == r['姓名']
                            if any(mask_p) and any(mask_e):
                                rate = clean_val(df_emp.loc[mask_e, '加班時薪'].values[0])
                                old_add, old_cash = clean_val(df_pay.loc[mask_p, '本月加班時數'].values[0]), clean_val(df_pay.loc[mask_p, '換錢時數'].values[0])
                                new_add, new_cash = clean_val(r.get('本月加班時數', 0)), clean_val(r.get('換錢時數', 0))
                                df_emp.loc[mask_e, '補休餘額'] = clean_val(df_emp.loc[mask_e, '補休餘額'].values[0]) + (new_add - old_add) - (new_cash - old_cash)
                                df_pay.loc[mask_p, '本月加班時數'], df_pay.loc[mask_p, '換錢時數'] = new_add, new_cash
                                df_pay.loc[mask_p, '加班津貼'] = float(round(new_cash * rate)) 
                                for col in ALL_VAR_COLS + ['備註']: 
                                    if col != '加班津貼' and col in r: df_pay.loc[mask_p, col] = r[col]
                        conn.update(worksheet=PAY_SHEET, data=df_pay); conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.success("完成")
                    
                    c1, c2, c3, c4 = st.columns(4)
                    with c1: st.download_button("📥 藥局 CSV", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp), f"Phar_{target_m}.csv")
                    with c2: st.download_button("📥 個管師 CSV", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp), f"Case_{target_m}.csv")
                    with c3:
                        if st.button("📧 寄送藥局 Email"):
                            count = 0
                            for _, r in ed_p.iterrows():
                                if not pd.isna(r.get('電子郵件')) and str(r.get('電子郵件')).strip() != "":
                                    d = {
                                        "本薪": r.get('本薪', 0),
                                        "績效獎金(評估表現發放)": r.get('績效獎金(評估表現發放)', 0),
                                        "保障獎金": r.get('保障獎金', 0),
                                        "固定加班津貼": r.get('固定加班津貼', 0),
                                        "執照津貼": r.get('執照津貼', 0),
                                        "車資補貼": r.get('車資補貼', 0),
                                        "加班費": r.get('加班費', 0)
                                    }
                                    for b in PHARMACY_VAR: d[b] = r.get(b, 0)
                                    d.update({"本月加班時數": r.get('本月加班時數', 0), "換錢時數": r.get('換錢時數', 0), "勞健保扣款": r.get('勞健保個人負擔', 0), "實領總額": r.get('應付金額', 0), "備註說明": r.get('備註', '')})
                                    if send_salary_email(r['電子郵件'], r['姓名'], target_m, d): count += 1
                            st.success(f"✅ 已成功發送 {count} 封【藥局】薪資明細郵件！")
                    with c4:
                        if st.button("📧 寄送個管師 Email"):
                            count = 0
                            for _, r in ed_c.iterrows():
                                if not pd.isna(r.get('電子郵件')) and str(r.get('電子郵件')).strip() != "":
                                    d = {
                                        "本薪": r.get('本薪', 0),
                                        "績效獎金(評估表現發放)": r.get('績效獎金(評估表現發放)', 0),
                                        "保障獎金": r.get('保障獎金', 0),
                                        "固定加班津貼": r.get('固定加班津貼', 0),
                                        "執照津貼": r.get('執照津貼', 0),
                                        "車資補貼": r.get('車資補貼', 0),
                                        "加班費": r.get('加班費', 0)
                                    }
                                    for b in CASE_MGR_VAR: d[b] = r.get(b, 0)
                                    d.update({"本月加班時數": r.get('本月加班時數', 0), "換錢時數": r.get('換錢時數', 0), "勞健保扣款": r.get('勞健保個人負擔', 0), "實領總額": r.get('應付金額', 0), "備註說明": r.get('備註', '')})
                                    if send_salary_email(r['電子郵件'], r['姓名'], target_m, d): count += 1
                            st.success(f"✅ 已成功發送 {count} 封【個管師】薪資明細郵件！")

                elif role == 3: # --- 💡 主管雙軌視角 ---
                    mgr_type = st.session_state.mgr_type
                    cols_from_emp = ['單位', '店別', '補休餘額', '剩餘特休時數', '加班時薪']
                    mgr_view = curr.copy()
                    mgr_view = mgr_view.drop(columns=[c for c in cols_from_emp if c in mgr_view.columns], errors='ignore')
                    mgr_view = mgr_view.merge(df_emp[['姓名'] + [c for c in cols_from_emp if c in df_emp.columns]], on='姓名', how='left')
                    mgr_view.rename(columns={'補休餘額': '現有補休', '剩餘特休時數': '現有特休'}, inplace=True)
                    
                    if shop == "ALL":
                        mgr_view = mgr_view[mgr_view['單位'] == mgr_type]
                    else:
                        mgr_view = mgr_view[(mgr_view['店別'].astype(str).str.zfill(2) == shop) & (mgr_view['單位'] == mgr_type)]
                    
                    var_cols = PHARMACY_VAR if mgr_type == "藥局" else CASE_MGR_VAR
                    edit_cols = ["月份", "店別", "姓名", "現有特休", "現有補休", "本月加班時數", "換錢時數"] + var_cols + ["備註"]
                    
                    for col in edit_cols:
                        if col not in mgr_view.columns: mgr_view[col] = "" if col in ["月份", "店別", "姓名", "備註"] else 0.0
                        if col not in ["月份", "店別", "姓名", "備註"]: mgr_view[col] = pd.to_numeric(mgr_view[col], errors='coerce').fillna(0.0)
                    
                    st.subheader(f"💰 {mgr_type}發薪作業 ({'總管' if shop=='ALL' else '店長'}權限)")
                    if not mgr_view.empty:
                        ed_mgr = st.data_editor(mgr_view[edit_cols], disabled=["月份", "店別", "姓名", "現有特休", "現有補休"] if not is_locked else edit_cols, key="mp")
                        if st.button(f"💾 {mgr_type}存檔同步") and not is_locked:
                            for _, row in ed_mgr.iterrows():
                                mask_p, mask_e = (df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名']), df_emp['姓名'] == row['姓名']
                                if any(mask_p) and any(mask_e):
                                    rate = clean_val(df_emp.loc[mask_e, '加班時薪'].values[0])
                                    old_add, old_cash = clean_val(df_pay.loc[mask_p, '本月加班時數'].values[0]), clean_val(df_pay.loc[mask_p, '換錢時數'].values[0])
                                    new_add, new_cash = clean_val(row.get('本月加班時數', 0)), clean_val(row.get('換錢時數', 0))
                                    df_emp.loc[mask_e, '補休餘額'] = clean_val(df_emp.loc[mask_e, '補休餘額'].values[0]) + (new_add - old_add) - (new_cash - old_cash)
                                    df_pay.loc[mask_p, '本月加班時數'], df_pay.loc[mask_p, '換錢時數'] = new_add, new_cash
                                    df_pay.loc[mask_p, '加班津貼'] = float(round(new_cash * rate))
                                    for col in var_cols + ['備註']: df_pay.loc[mask_p, col] = row[col]
                            conn.update(worksheet=PAY_SHEET, data=df_pay); conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.success(f"{mgr_type}存檔完成")
                    else: st.info(f"尚無{mgr_type}人員資料。")

        if role == 1:
            with tabs[1]:
                c1, c2 = st.columns(2)
                with c1:
                    p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                    for idx, row in p_l.iterrows():
                        if st.button(f"✅ 核准 {row['姓名']} - {row['類別']}", key=f"la_{idx}"):
                            rule = LEAVE_TYPES.get(row['類別'], {})
                            if rule.get('deduct') in df_emp.columns:
                                df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct']] -= clean_val(row['時數'])
                                conn.update(worksheet=EMP_SHEET, data=df_emp)
                            df_lv.at[idx, '狀態'] = '已核准'; conn.update(worksheet=LEAVE_SHEET, data=df_lv); st.cache_data.clear(); st.rerun()
                with c2:
                    p_o = df_ot[df_ot['狀態'] == '待審核'] if '狀態' in df_ot.columns else pd.DataFrame()
                    for idx, row in p_o.iterrows():
                        if st.button(f"✅ 同意 {row['姓名']} - {row['處理方式']}", key=f"oa_{idx}"):
                            if row['處理方式'] == '累積補休': df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] += clean_val(row['時數'])
                            else:
                                mask = (df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == row['姓名'])
                                if any(mask):
                                    rate = clean_val(df_emp[df_emp['姓名'] == row['姓名']].iloc[0].get('加班時薪', 0))
                                    df_pay.loc[mask, '加班津貼'] += float(round(rate * clean_val(row['時數'])))
                                    df_emp.loc[df_emp['姓名'] == row['姓名'], '補休餘額'] -= clean_val(row['時數'])
                                    conn.update(worksheet=PAY_SHEET, data=df_pay)
                            df_ot.at[idx, '狀態'] = '已執行'; conn.update(worksheet=OT_SHEET, data=df_ot); conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.rerun()

            with tabs[2]:
                st.subheader("👤 員工主資料與特休維護")
                
                with st.expander("🎁 勞基法特休自動結算系統"):
                    st.info("💡 系統會追蹤每人的「累計應得特休」。只有當年資跨階（如滿半年變一年），才會把「新增時數」加進餘額裡。重複點擊絕對不會洗掉已請假的扣除紀錄！")
                    if st.button("⚡ 依勞基法年資結算特休"):
                        count = 0
                        for idx, row in df_emp.iterrows():
                            current_entitlement = get_annual_leave_hours(row.get('加保日期'))
                            historical_entitlement = clean_val(row.get('累計應得特休', 0))
                            
                            if historical_entitlement == 0:
                                if clean_val(row.get('剩餘特休時數', 0)) == 0:
                                    df_emp.at[idx, '剩餘特休時數'] = current_entitlement
                                df_emp.at[idx, '累計應得特休'] = current_entitlement
                                count += 1
                            elif current_entitlement > historical_entitlement:
                                diff = current_entitlement - historical_entitlement
                                df_emp.at[idx, '剩餘特休時數'] = clean_val(row.get('剩餘特休時數', 0)) + diff
                                df_emp.at[idx, '累計應得特休'] = current_entitlement
                                count += 1
                        
                        if count > 0:
                            conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear()
                            st.success(f"✅ 結算完成！共有 {count} 位同仁的特休獲得更新或補發。")
                        else:
                            st.warning("目前所有同仁的特休時數皆已符合年資標準，無需重複發放。")
                
                ed_emp = st.data_editor(df_emp, num_rows="dynamic", key="b_main")
                if st.button("💾 儲存員工資料更新"):
                    conn.update(worksheet=EMP_SHEET, data=ed_emp); st.cache_data.clear(); st.success("✅ 員工資料已更新！")

            with tabs[3]:
                st.subheader("🏥 勞健保紀錄維護")
                ed_ins_boss = st.data_editor(df_ins, num_rows="dynamic", key="b_ins")
                if st.button("💾 儲存勞健保更新"):
                    conn.update(worksheet=INS_SHEET, data=ed_ins_boss); st.cache_data.clear(); st.success("✅ 勞健保資料已更新！")

            with tabs[4]: st.data_editor(df_acc, num_rows="dynamic", key="b_acc")

        if role == 4:
            with tabs[0]:
                ed_acct = st.data_editor(df_ins, num_rows="dynamic", key="ac_view")
                if st.button("💾 會計更新"): conn.update(worksheet=INS_SHEET, data=ed_acct); st.cache_data.clear(); st.success("OK")

if __name__ == "__main__":
    main()
