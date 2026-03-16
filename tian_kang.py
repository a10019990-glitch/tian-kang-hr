import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import re
import hashlib

# --- 1. 雲端與頁面設定 ---
SHEET_ID = "1TcrNfnSKj7hMd0LOXipBD9eKAft6yU7YnhZNX6rtPhg"
PAY_SHEET = "salary_data"
EMP_SHEET = "emp_info"
INS_SHEET = "ins_info"
ACC_SHEET = "user_accounts" # 新增帳號存儲分頁

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 加密工具：不存明碼，保護員工隱私
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c})
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    mapping.update({c: "身分證" for c in df.columns if "身分證" in c})
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 薪資查詢系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 讀取資料
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl="0"))
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    # --- 登入與註冊邏輯 ---
    if 'auth' not in st.session_state:
        mode = st.radio("選擇操作", ["員工登入", "管理員登入", "新員工註冊"])
        
        if mode == "員工登入":
            user_acc = st.text_input("帳號")
            user_pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                hashed_pw = hash_password(user_pw)
                # 檢查帳號密碼
                match = df_acc[(df_acc['帳號'] == user_acc) & (df_acc['密碼'] == hashed_pw)]
                if not match.empty:
                    st.session_state.auth = 5 # 員工權限
                    st.session_state.user_name = match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("帳號或密碼錯誤")

        elif mode == "管理員登入":
            admin_user = st.text_input("管理員帳號 (boss 或 mgr_xx)")
            if st.button("進入管理後台"):
                if admin_user == "boss":
                    st.session_state.auth, st.session_state.shop = 1, "ALL"
                    st.rerun()
                elif admin_user.startswith("mgr_"):
                    shop_id = re.findall(r'\d+', admin_user)
                    st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "00"
                    st.rerun()
        
        elif mode == "新員工註冊":
            st.subheader("📝 首次使用註冊")
            reg_name = st.text_input("真實姓名")
            reg_id = st.text_input("身分證字號")
            reg_email = st.text_input("Email")
            new_acc = st.text_input("設定新帳號")
            new_pw = st.text_input("設定新密碼", type="password")
            
            if st.button("完成註冊並寫入雲端"):
                # 驗證是否為公司員工 (比對 emp_info)
                check_emp = df_emp[(df_emp['姓名'] == reg_name) & (df_emp['身分證'] == reg_id)]
                if not check_emp.empty:
                    new_user = pd.DataFrame({
                        "姓名": [reg_name], "身分證字號": [reg_id], "Email": [reg_email],
                        "帳號": [new_acc], "密碼": [hash_password(new_pw)]
                    })
                    conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_user], ignore_index=True))
                    st.success("註冊成功！請切換到登入模式。")
                else:
                    st.error("驗證失敗：姓名或身分證字號與公司資料不符。")
        return

    # --- 登入後的畫面 ---
    role = st.session_state.auth
    
    # 【權限 A：員工個人視角】
    if role == 5:
        user_name = st.session_state.user_name
        st.subheader(f"👋 你好，{user_name}！這是你的個人薪資明細")
        
        # 篩選個人資料
        personal_pay = df_pay[df_pay['姓名'] == user_name].copy()
        if not personal_pay.empty:
            # 合併計算資料
            personal_pay = personal_pay.merge(df_emp[['姓名', '基本薪資合計']], on='姓名', how='left')
            personal_pay = personal_pay.merge(df_ins[['姓名', '勞健保自負額']], on='姓名', how='left')
            
            bonus_cols = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            for c in bonus_cols + ['基本薪資合計', '勞健保自負額']:
                personal_pay[c] = pd.to_numeric(personal_pay[c], errors='coerce').fillna(0)
            
            personal_pay['實領金額'] = (personal_pay['基本薪資合計'] + personal_pay[bonus_cols].sum(axis=1)) - personal_pay['勞健保自負額']
            
            # 只顯示該員工可以看的部分
            show_cols = ["月份", "店別", "基本薪資合計"] + bonus_cols + ["勞健保自負額", "實領金額", "備註"]
            st.dataframe(personal_pay[show_cols])
        else:
            st.info("目前尚無你的薪資紀錄。")
            
        if st.button("登出"):
            del st.session_state['auth']; st.rerun()

    # 【權限 B：老闆/店長視角】 (維持原有所有功能)
    else:
        shop = st.session_state.shop
        tab1, tab2, tab3, tab4 = st.tabs(["💰 薪資作業", "👤 員工資料", "🏥 勞健保明細", "🔑 帳號管理"])
        
        with tab1:
            # (這裡保留你之前所有的薪資核對、自動建立月份、銀行匯出功能代碼...)
            st.write(f"管理模式：{shop}")
            # ... (中間代碼省略，請維持上一版本的 Tab 1 內容)

        with tab4:
            st.subheader("🔑 系統帳號清單")
            st.dataframe(df_acc)
