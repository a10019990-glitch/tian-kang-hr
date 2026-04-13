import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. 雲端與基本設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts"
LOCK_SHEET = "lock_status"
LEAVE_SHEET = "leave_requests"
OT_SHEET = "ot_requests"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# --- 2. 假別定義 (新增育嬰留停) ---
LEAVE_TYPES = {
    "特休": {"pay_ratio": 0.0, "deduct_balance": "剩餘特休時數", "desc": "全薪，扣除特休餘額"},
    "補休": {"pay_ratio": 0.0, "deduct_balance": "補休餘額", "desc": "全薪，扣除補休餘額"},
    "病假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "半薪 (一年 30 天內)"},
    "生理假(半薪)": {"pay_ratio": 0.5, "deduct_balance": None, "desc": "半薪 (每月 1 天)"},
    "事假(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "無薪"},
    "婚假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "全薪 (8 天)"},
    "喪假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "全薪 (依對象 3~8 天)"},
    "產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend", "deduct_balance": None, "desc": "8 週"},
    "流產假(年資滿半年全薪/未滿半薪)": {"pay_ratio": "Tenure_Depend", "deduct_balance": None, "desc": "依週數給假"},
    "產檢假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7 天 (可分小時請)"},
    "陪產檢及陪產假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "7 天 (可分小時請)"},
    "產前假(全薪)": {"pay_ratio": 0.0, "deduct_balance": None, "desc": "6 天"},
    "育嬰留職停薪(無薪)": {"pay_ratio": 1.0, "deduct_balance": None, "desc": "滿半年可申請，最長 2 年"}
}

# --- 3. 核心工具 ---
def get_seniority(start_date_str):
    try:
        start_date = datetime.strptime(str(start_date_str), "%Y-%m-%d")
        delta = datetime.now() - start_date
        return max(0, delta.days / 365.25)
    except: return 0

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
        "勞健保個人負擔": "勞健保個人負擔", "加保日期": "加保日期", "補休餘額": "補休餘額",
        "剩餘特休時數": "剩餘特休時數", "單位": "單位", "店別": "店別", "基本薪資合計": "基本薪資合計", 
        "加班時薪": "加班時薪", "執照津貼": "執照津貼", "車資補貼": "車資補貼", "備註": "備註", "狀態": "狀態"
    }
    new_mapping = {c: mapping[k] for c in df.columns for k in mapping if k in c}
    df = df.rename(columns=new_mapping)
    if "姓名" in df.columns: df["姓名"] = df["姓名"].astype(str).str.replace(r'\s+', '', regex=True)
    return df.loc[:, ~df.columns.duplicated()]

def main():
    st.title("🚀 天康連鎖藥局 - 勞基法全功能人事系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    # --- 數據讀取 ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=0), expected_cols=['姓名','單位','加班時薪','補休餘額','剩餘特休時數'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=0))
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=0))
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=0))
        df_leave = robust_clean(conn.read(worksheet=LEAVE_SHEET, ttl=0))
        try: df_lock = robust_clean(conn.read(worksheet=LOCK_SHEET, ttl=0))
        except: df_lock = pd.DataFrame(columns=['月份', '狀態'])
    except Exception as e: st.error(f"連線失敗: {e}"); st.stop()

    if 'auth' not in st.session_state:
        # (登入邏輯維持不變)
        mode = st.radio("入口選擇", ["管理端登入", "員工查詢", "新帳號註冊"], horizontal=True)
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
        elif mode == "員工查詢":
            e_acc = st.text_input("帳號"); e_pw = st.text_input("密碼", type="password")
            if st.button("查詢登入"):
                m = df_acc[(df_acc['帳號'] == e_acc) & (df_acc['密碼'] == hash_password(e_pw))]
                if not m.empty: st.session_state.auth, st.session_state.user_name, st.session_state.shop = 5, m.iloc[0]['姓名'], "PERSONAL"; st.rerun()
        return

    role, shop = st.session_state.auth, st.session_state.shop

    if role == 5: # --- 員工專區 ---
        name = st.session_state.user_name.replace(" ", "")
        personal_ins = df_ins[df_ins['姓名'] == name]
        start_date = personal_ins.sort_values('加保日期').iloc[0]['加保日期'] if not personal_ins.empty else "N/A"
        yrs = get_seniority(start_date)
        
        st.subheader(f"👋 {name} 同仁")
        st.sidebar.info(f"🎖️ **年資**：{yrs:.2f} 年\n\n🗓️ **加保日期**：{start_date}")

        tab_e = st.tabs(["💰 薪資單", "📅 差勤申請與記錄"])
        with tab_e[1]:
            e_info = df_emp[df_emp['姓名'] == name].iloc[0]
            c1, c2 = st.columns(2)
            with c1:
                st.metric("補休餘額", f"{clean_val(e_info['補休餘額'])} hr")
                with st.form("l_f_plus"):
                    lt = st.selectbox("請假假別 (含育嬰留停)", list(LEAVE_TYPES.keys()))
                    st.caption(f"💡 假別說明：{LEAVE_TYPES[lt]['desc']}")
                    ld, lh, lr = st.date_input("日期"), st.number_input("小時/天數換算小時", 0.5, 480.0, 1.0, 0.5), st.text_area("理由")
                    if st.form_submit_button("提交申請"):
                        new_l = pd.DataFrame({"日期":[str(ld)],"姓名":[name],"類別":[lt],"時數":[lh],"事由":[lr],"狀態":["待審核"]})
                        conn.update(worksheet=LEAVE_SHEET, data=pd.concat([df_leave, new_l], ignore_index=True)); st.success("已送審")
            with c2:
                st.dataframe(df_leave[df_leave['姓名'] == name].sort_values('日期', ascending=False))

    else: # --- 管理端 ---
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()
        tabs = st.tabs(["💰 薪資作業", "📑 假別與加班審核", "👤 員工主表"])

        with tabs[1]: # 審核案件
            if role == 1:
                st.subheader("📑 待核准申請單 (Boss)")
                p_l = df_leave[df_leave['狀態'] == '待審核']
                if not p_l.empty:
                    for idx, row in p_l.iterrows():
                        with st.expander(f"【{row['類別']}】{row['姓名']} | {row['時數']}hr"):
                            rule = LEAVE_TYPES.get(row['類別'], {"pay_ratio": 0.0, "deduct_balance": None})
                            e_data = df_emp[df_emp['姓名'] == row['姓名']].iloc[0]
                            
                            p_ins = df_ins[df_ins['姓名'] == row['姓名']]
                            s_date = p_ins.sort_values('加保日期').iloc[0]['加保日期'] if not p_ins.empty else "N/A"
                            yrs = get_seniority(s_date)
                            
                            st.write(f"到職日：{s_date} (年資 {yrs:.2f} 年)")
                            st.write(f"事由：{row['事由']}")

                            # 💡 育嬰留停邏輯檢查
                            if "育嬰留職停薪" in row['類別']:
                                if yrs < 0.5:
                                    st.error("⚠️ 法律提醒：該同仁年資未滿 6 個月，不符合法定育嬰留停強制門檻。")
                                else:
                                    st.success("✅ 法律確認：該同仁年資已滿 6 個月，符合申請資格。")
                                st.warning("📢 提醒：育嬰留停期間公司不需支付薪資。")

                            # 💡 其他假別扣薪提醒 (略)
                            
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 核准", key=f"la_{idx}"):
                                if rule['deduct_balance']:
                                    df_emp.loc[df_emp['姓名'] == row['姓名'], rule['deduct_balance']] -= clean_val(row['時數'])
                                    conn.update(worksheet=EMP_SHEET, data=df_emp)
                                df_leave.at[idx, '狀態'] = '已核准'
                                conn.update(worksheet=LEAVE_SHEET, data=df_leave); st.rerun()
                            if c2.button("❌ 拒絕", key=f"lr_{idx}"):
                                df_leave.at[idx, '狀態'] = '已拒絕'
                                conn.update(worksheet=LEAVE_SHEET, data=df_leave); st.rerun()
