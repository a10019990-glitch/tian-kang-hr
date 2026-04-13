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

# 💡 特休與補休獨立扣除對應欄位
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

def generate_bank_csv(df_source, df_employee):
    cols_to_add = ['身分證', '收款帳號']
    df_clean = df_source.drop(columns=[c for c in cols_to_add if c in df_source.columns], errors='ignore')
    emp_sub = df_employee[['姓名'] + [c for c in cols_to_add if c in df_employee.columns]].drop_duplicates('姓名')
    
    f_df = df_clean.merge(emp_sub, on='姓名', how='left')
    for c in cols_to_add:
        if c not in f_df.columns: f_df[c] = ""
        
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"), "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"], "收款帳號": f_df["收款帳號"],
        "交易金額": f_df.get("應付金額", 0), "附言": "轉帳存入", "付款性質": "轉帳存入"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def send_salary_email(to_email, name, month, total):
    S_EMAIL, S_PW = "a10019990@gmail.com", "aczy dkos wjnd cgkm"
    msg = MIMEMultipart(); msg["From"] = f"天康管理部 <{S_EMAIL}>"; msg["To"] = str(to_email)
    msg["Subject"] = f"【薪資通知】{month} 薪資明細 - {name}"
    html = f"<html><body><h3>👋 {name} 同仁您好：</h3><p>您 {month} 月份的實領總額為：<b>{total}</b> 元。</p><p>詳情請登入系統查詢。</p></body></html>"
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s: s.login(S_EMAIL, S_PW); s.send_message(msg); return True
    except: return False

# --- 4. 數據讀取與 429 流量防禦 ---
@st.cache_data(ttl=120)
def fetch_all_data():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        std_map = {"月份": "月份", "姓名": "姓名", "身分證": "身分證", "加保日期": "加保日期", "補休餘額": "補休餘額", "剩餘特休時數": "剩餘特休時數", "加班時薪": "加班時薪", "基本薪資合計": "基本薪資合計", "單位": "單位", "店別": "店別", "生效月份": "生效月份", "執照津貼": "執照津貼", "車資補貼": "車資補貼", "電子郵件": "電子郵件", "收款帳號": "收款帳號"}
        std_cols = list(std_map.values())
        
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=30), std_map, std_cols)
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=30), std_map, std_cols + ['本月加班時數', '換錢時數', '加班津貼'] + ALL_VAR_COLS)
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=30), std_map, std_cols + ['勞健保個人負擔'])
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=30), None, ["帳號", "密碼", "姓名", "身分證"])
        df_lv = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=30), None, ["日期", "姓名", "類別", "時數", "事由", "狀態"])
        df_ot = robust_clean(conn.read(worksheet=OT_SHEET, ttl=30), None, ["日期", "姓名", "時數", "處理方式", "原因", "狀態"])
        try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=30), None, ["月份", "狀態"])
        except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
        
        # 強制數值型態，包含剩餘特休時數
        for col in ['本月加班時數', '換錢時數', '加班津貼', '補休餘額', '剩餘特休時數', '基本薪資合計', '加班時薪']:
            if col in df_pay.columns: df_pay[col] = pd.to_numeric(df_pay[col], errors='coerce').fillna(0.0)
            if col in df_emp.columns: df_emp[col] = pd.to_numeric(df_emp[col], errors='coerce').fillna(0.0)
            
        return df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock
    except Exception as e:
        if "429" in str(e): st.error("🚨 API 配額用盡，請稍候 30 秒再重新載入網頁。"); st.stop()
        else: raise e

def main():
    st.title("🚀 天康藥局管理系統 (防彈穩定版)")
    
    if st.sidebar.button("🔄 同步資料 (清除快取)"): 
        st.cache_data.clear(); st.rerun()

    try:
        df_emp, df_pay, df_ins, df_acc, df_lv, df_ot, df_lock = fetch_all_data()
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception as e:
        st.error("🚨 系統連線暫時受到限制。請等待約 30 秒後重新載入。")
        st.stop()

    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["管理端登入", "員工查詢", "新帳號註冊"], horizontal=True)
        if mode == "管理端登入":
            acc = st.text_input("帳號"); pw = st.text_input("密碼", type="password")
            if st.button("登入管理"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    if acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif acc.startswith("mgr_"): sid = re.findall(r'\d+', acc); st.session_state.auth, st.session_state.shop = 3, (sid[0].zfill(2) if sid else "00")
                    st.rerun()
        elif mode == "員工查詢":
            e_acc = st.text_input("員工帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("登入查詢"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    # --- 5. 員工專區 ---
    if role == 5:
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
                base = clean_val(e_info.get('基本薪資合計', 0)); lic = clean_val(e_info.get('執照津貼', 0)); trans = clean_val(e_info.get('車資補貼', 0))
                p_pay['基本薪資合計'] = base; p_pay['執照津貼'] = lic; p_pay['車資補貼'] = trans
                p_pay['實領總額'] = (base + lic + trans + p_pay[b_cols].sum(axis=1) + p_pay['加班津貼']) - p_pay['勞健保個人負擔']
                st.dataframe(p_pay[['月份', '基本薪資合計', '執照津貼', '車資補貼'] + b_cols + ['本月加班時數', '換錢時數', '加班津貼', '勞健保個人負擔', '實領總額', '備註']], use_container_width=True)
            else: st.warning("目前尚無您的紀錄。")

        with t2:
            ebal = df_emp[df_emp['姓名']==name].iloc[0] if not df_emp[df_emp['姓名']==name].empty else {}
            
            # 💡 特休與補休雙軌顯示
            c1, c2 = st.columns(2)
            c1.metric("🎯 特休餘額", f"{clean_val(ebal.get('剩餘特休時數',0))} hr")
            c2.metric("⚡ 補休餘額", f"{clean_val(ebal.get('補休餘額',0))} hr")
            
            with st.form("emp_apply"):
                lt = st.selectbox("申請項目", list(LEAVE_TYPES.keys()) + ["加班預約", "補休轉現金"]); ld, lh, lr = st.date_input("日期"), st.number_input("小時", 0.5, 12.0, 1.0, 0.5), st.text_area("理由")
                if st.form_submit_button("送出申請"):
                    if "加班" in lt: conn.update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["累積補休"],"原因":[lr],"狀態":["待審核"]})], ignore_index=True))
                    elif "補休" in lt: conn.update(worksheet=OT_SHEET, data=pd.concat([df_ot, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"時數":[lh],"處理方式":["換錢"],"原因":["補休核現"],"狀態":["待審核"]})], ignore_index=True))
                    else: conn.update(worksheet=LEAVE_SHEET, data=pd.concat([df_lv, pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})], ignore_index=True))
                    st.cache_data.clear(); st.success("已提交")
        with t3: st.write("請假紀錄"); st.dataframe(df_lv[df_lv['姓名']==name]); st.write("加班紀錄"); st.dataframe(df_ot[df_ot['姓名']==name])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    # --- 6. 管理端 ---
    else:
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
                
                if role == 1: # 🚀 老闆月份管理
                    with st.sidebar.expander("🛠️ 月份管理系統"):
                        new_m = st.text_input("新增 (YYYY-MM)", "2026-06")
                        if st.button("🚀 建立月份"):
                            l_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            new_r = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "備註":df_emp[['姓名']].merge(l_rem, on='姓名', how='left')["備註"].fillna("").tolist()})
                            for c in ALL_VAR_COLS + ['本月加班時數', '換錢時數']: new_r[c] = 0.0
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        if st.button("🔒 鎖定/解鎖"):
                            new_lock = pd.DataFrame({"月份":[target_m],"狀態":["OPEN" if is_locked else "LOCKED"]})
                            others = df_lock[df_lock['月份'].astype(str) != target_m]
                            conn.update(worksheet=LOCK_SHEET, data=pd.concat([others, new_lock], ignore_index=True)); st.cache_data.clear(); st.rerun()
                        del_m = st.selectbox("刪除月份", all_m, key="del_box")
                        if st.button("🔥 執行刪除") and st.checkbox("確認"):
                            conn.update(worksheet=PAY_SHEET, data=df_pay[df_pay['月份'].astype(str) != del_m]); st.cache_data.clear(); st.rerun()

                curr = df_pay[df_pay['月份'].astype(str) == target_m].copy()
                
                if role == 1: # --- 老闆視角 ---
                    # 💡 加入剩餘特休時數並重新命名
                    cols_from_emp = ['單位','基本薪資合計','執照津貼','車資補貼','電子郵件','加班時薪', '補休餘額', '剩餘特休時數', '店別']
                    curr = curr.drop(columns=[c for c in cols_from_emp if c in curr.columns], errors='ignore')
                    
                    emp_sub = df_emp[['姓名'] + [c for c in cols_from_emp if c in df_emp.columns]].copy()
                    curr = curr.merge(emp_sub, on='姓名', how='left')
                    
                    if '補休餘額' in curr.columns: curr.rename(columns={'補休餘額': '現有補休'}, inplace=True)
                    else: curr['現有補休'] = 0.0
                    
                    if '剩餘特休時數' in curr.columns: curr.rename(columns={'剩餘特休時數': '現有特休'}, inplace=True)
                    else: curr['現有特休'] = 0.0
                    
                    l_ins_list = []
                    for n in curr['姓名']:
                        v = df_ins[(df_ins['姓名'] == n) & (df_ins['生效月份'].astype(str) <= target_m)] if '生效月份' in df_ins.columns else pd.DataFrame()
                        l_ins_list.append(v.sort_values('生效月份', ascending=False).iloc[0].reindex(['姓名','勞健保個人負擔'], fill_value=0) if not v.empty else pd.Series([n,0], index=['姓名','勞健保個人負擔']))
                    
                    ins_df = pd.DataFrame(l_ins_list)
                    if not ins_df.empty: curr = curr.merge(ins_df, on='姓名', how='left')
                    else: curr['勞健保個人負擔'] = 0.0
                    
                    calc_cols = ALL_VAR_COLS + ['基本薪資合計', '勞健保個人負擔', '本月加班時數', '換錢時數', '現有補休', '現有特休', '執照津貼', '車資補貼']
                    for c in calc_cols: 
                        if c not in curr.columns: curr[c] = 0.0
                        curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0.0)
                        
                    curr['應付金額'] = (curr['基本薪資合計'] + curr['執照津貼'] + curr['車資補貼'] + curr[ALL_VAR_COLS].sum(axis=1)) - curr['勞健保個人負擔']
                    
                    if '單位' not in curr.columns: curr['單位'] = ""
                    
                    st.subheader("💊 藥局組")
                    ed_p = st.data_editor(curr[curr['單位'] == "藥局"][['月份','店別','姓名','現有特休','現有補休','本月加班時數','換錢時數','基本薪資合計','應付金額','電子郵件'] + PHARMACY_VAR + ['加班津貼','備註']], disabled=["現有特休", "現有補休"] if not is_locked else True, key="bp")
                    st.subheader("📂 個管師組")
                    ed_c = st.data_editor(curr[curr['單位'] == "個管師"][['月份','店別','姓名','現有特休','現有補休','本月加班時數','換錢時數','基本薪資合計','應付金額','電子郵件'] + CASE_MGR_VAR + ['加班津貼','備註']], disabled=["現有特休", "現有補休"] if not is_locked else True, key="bc")
                    
                    if st.button("💾 老闆同步存檔") and not is_locked:
                        for _, r in pd.concat([ed_p, ed_c]).iterrows():
                            emp_name = r['姓名']
                            mask_p = (df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == emp_name)
                            mask_e = df_emp['姓名'] == emp_name
                            
                            if any(mask_p) and any(mask_e):
                                rate = clean_val(df_emp.loc[mask_e, '加班時薪'].values[0]) if '加班時薪' in df_emp.columns else 0
                                old_add = clean_val(df_pay.loc[mask_p, '本月加班時數'].values[0]) if '本月加班時數' in df_pay.columns else 0
                                old_cash = clean_val(df_pay.loc[mask_p, '換錢時數'].values[0]) if '換錢時數' in df_pay.columns else 0
                                new_add = clean_val(r.get('本月加班時數', 0))
                                new_cash = clean_val(r.get('換錢時數', 0))

                                df_emp.loc[mask_e, '補休餘額'] = clean_val(df_emp.loc[mask_e, '補休餘額'].values[0]) + (new_add - old_add) - (new_cash - old_cash)
                                df_pay.loc[mask_p, '本月加班時數'] = new_add
                                df_pay.loc[mask_p, '換錢時數'] = new_cash
                                df_pay.loc[mask_p, '加班津貼'] = float(round(new_cash * rate))

                                for col in ALL_VAR_COLS + ['備註']:
                                    if col != '加班津貼' and col in r: df_pay.loc[mask_p, col] = r[col]
                                    
                        conn.update(worksheet=PAY_SHEET, data=df_pay)
                        conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.success("完成")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1: st.download_button("📥 藥局 CSV", generate_bank_csv(curr[curr['單位'] == "藥局"], df_emp), f"Phar_{target_m}.csv")
                    with c2: st.download_button("📥 個管師 CSV", generate_bank_csv(curr[curr['單位'] == "個管師"], df_emp), f"Case_{target_m}.csv")
                    with c3:
                        if st.button("📧 批量寄送 Email"):
                            for _, r in pd.concat([ed_p, ed_c]).iterrows(): send_salary_email(r.get('電子郵件'), r['姓名'], target_m, r.get('應付金額', 0))
                            st.success("✅ 完成")
                
                elif role == 3: # --- 💡 店長視角 ---
                    cols_from_emp = ['單位', '店別', '補休餘額', '剩餘特休時數', '加班時薪']
                    mgr_view = curr.copy()
                    mgr_view = mgr_view.drop(columns=[c for c in cols_from_emp if c in mgr_view.columns], errors='ignore')
                    
                    emp_sub = df_emp[['姓名'] + [c for c in cols_from_emp if c in df_emp.columns]].copy()
                    mgr_view = mgr_view.merge(emp_sub, on='姓名', how='left')
                    
                    if '補休餘額' in mgr_view.columns: mgr_view.rename(columns={'補休餘額': '現有補休'}, inplace=True)
                    else: mgr_view['現有補休'] = 0.0
                    
                    if '剩餘特休時數' in mgr_view.columns: mgr_view.rename(columns={'剩餘特休時數': '現有特休'}, inplace=True)
                    else: mgr_view['現有特休'] = 0.0
                    
                    if '店別' not in mgr_view.columns: mgr_view['店別'] = ""
                    if '單位' not in mgr_view.columns: mgr_view['單位'] = ""
                    
                    mgr_view = mgr_view[(mgr_view['店別'].astype(str).str.zfill(2) == shop) & (mgr_view['單位'] == "藥局")]
                    
                    edit_cols = ["月份", "店別", "姓名", "現有特休", "現有補休", "本月加班時數", "換錢時數"] + PHARMACY_VAR + ["備註"]
                    
                    for col in edit_cols:
                        if col not in mgr_view.columns:
                            mgr_view[col] = "" if col in ["月份", "店別", "姓名", "備註"] else 0.0
                        if col not in ["月份", "店別", "姓名", "備註"]:
                            mgr_view[col] = pd.to_numeric(mgr_view[col], errors='coerce').fillna(0.0)
                    
                    st.subheader("💰 藥局發薪作業 (店長權限 - 個管師已隱藏)")
                    if not mgr_view.empty:
                        lock_state = edit_cols if is_locked else ["月份", "店別", "姓名", "現有特休", "現有補休"]
                        ed_mgr = st.data_editor(mgr_view[edit_cols], disabled=lock_state, key="mp")
                        
                        if st.button("💾 店長存檔同步") and not is_locked:
                            for _, row in ed_mgr.iterrows():
                                emp_name = row['姓名']
                                mask_p = (df_pay['月份'].astype(str) == target_m) & (df_pay['姓名'] == emp_name)
                                mask_e = df_emp['姓名'] == emp_name
                                
                                if any(mask_p) and any(mask_e):
                                    rate = clean_val(df_emp.loc[mask_e, '加班時薪'].values[0]) if '加班時薪' in df_emp.columns else 0
                                    old_add = clean_val(df_pay.loc[mask_p, '本月加班時數'].values[0]) if '本月加班時數' in df_pay.columns else 0
                                    old_cash = clean_val(df_pay.loc[mask_p, '換錢時數'].values[0]) if '換錢時數' in df_pay.columns else 0
                                    new_add = clean_val(row.get('本月加班時數', 0))
                                    new_cash = clean_val(row.get('換錢時數', 0))

                                    df_emp.loc[mask_e, '補休餘額'] = clean_val(df_emp.loc[mask_e, '補休餘額'].values[0]) + (new_add - old_add) - (new_cash - old_cash)
                                    df_pay.loc[mask_p, '本月加班時數'] = new_add
                                    df_pay.loc[mask_p, '換錢時數'] = new_cash
                                    df_pay.loc[mask_p, '加班津貼'] = float(round(new_cash * rate))

                                    for col in PHARMACY_VAR + ['備註']: 
                                        df_pay.loc[mask_p, col] = row[col]
                            
                            conn.update(worksheet=PAY_SHEET, data=df_pay)
                            conn.update(worksheet=EMP_SHEET, data=df_emp); st.cache_data.clear(); st.success("店長存檔完成")
                    else: st.info("本月份該店尚無藥局人員資料。")

        # --- Boss 專屬管理分頁 ---
        if role == 1:
            with tabs[1]:
                c1, c2 = st.columns(2)
                with c1:
                    p_l = df_lv[df_lv['狀態'] == '待審核'] if '狀態' in df_lv.columns else pd.DataFrame()
                    for idx, row in p_l.iterrows():
                        # 💡 依類別動態扣除特休或補休餘額
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

            with tabs[2]: st.data_editor(df_emp, num_rows="dynamic", key="b_main")
            with tabs[3]: st.data_editor(df_ins, num_rows="dynamic", key="b_ins")
            with tabs[4]: st.data_editor(df_acc, num_rows="dynamic", key="b_acc")

        # --- 會計專屬 ---
        if role == 4:
            with tabs[0]:
                ed_acct = st.data_editor(df_ins, num_rows="dynamic", key="ac_view")
                if st.button("💾 會計更新"): conn.update(worksheet=INS_SHEET, data=ed_acct); st.cache_data.clear(); st.success("OK")

if __name__ == "__main__":
    main()
