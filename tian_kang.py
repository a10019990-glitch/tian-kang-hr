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
ACC_SHEET = "user_accounts"

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 加密工具：SHA256
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# 核心：格式化店別與欄位清洗
def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c})
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    mapping.update({c: "身分證" for c in df.columns if "身分證" in c or "字號" in c})
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

def main():
    st.title("🚀 天康連鎖藥局 - 雲端管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 💡 解決 429 與崩潰問題：適度快取
    if st.sidebar.button("🔄 重新載入最新資料"):
        st.cache_data.clear()
        st.rerun()

    DEFAULT_TTL = 300 # 5分鐘快取

    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=DEFAULT_TTL))
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=DEFAULT_TTL))
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=DEFAULT_TTL))
        try:
            df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=DEFAULT_TTL))
        except:
            df_acc = pd.DataFrame(columns=["姓名", "身分證", "帳號", "密碼"])
    except Exception as e:
        st.error("❌ 雲端連線忙碌中，請稍候 30 秒再點選左側『重新載入』。")
        st.stop()

    # --- 登入控制 ---
    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["員工薪資查詢", "管理後台登入", "新帳號註冊"], horizontal=True)
        
        if mode == "員工薪資查詢":
            acc = st.text_input("請輸入帳號", key="login_acc")
            pw = st.text_input("請輸入密碼", type="password", key="login_pw")
            if st.button("執行登入"):
                if acc and pw:
                    match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                    if not match.empty:
                        st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                        st.rerun()
                    else: st.error("❌ 帳號或密碼錯誤")
                else: st.warning("⚠️ 請完整輸入資訊")

        elif mode == "管理後台登入":
            admin = st.text_input("管理員代號 (boss 或 mgr_xx)")
            if st.button("進入管理介面"):
                if admin == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"; st.rerun()
                elif admin.startswith("mgr_"): 
                    st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', admin)[0].zfill(2); st.rerun()
                else: st.error("❌ 無效帳號")

        elif mode == "新帳號註冊":
            st.info("💡 註冊小提醒：請設定 6 位數以上較複雜的密碼，避免瀏覽器跳出警告導致系統中斷。")
            with st.form("reg_form"): # 使用 Form 提高穩定性
                reg_name = st.text_input("姓名 (需與公司資料一致)")
                reg_id = st.text_input("身分證字號")
                reg_acc = st.text_input("設定登入帳號")
                reg_pw = st.text_input("設定登入密碼", type="password")
                submitted = st.form_submit_button("送出註冊")
                
                if submitted:
                    # 1. 檢查是否已註冊過
                    if not df_acc[df_acc['帳號'] == reg_acc].empty:
                        st.error("❌ 此帳號已被使用，請更換。")
                    # 2. 驗證是否為公司員工
                    elif not df_emp[(df_emp['姓名']==reg_name) & (df_emp['身分證']==reg_id)].empty:
                        try:
                            new_row = pd.DataFrame({"姓名":[reg_name], "身分證":[reg_id], "帳號":[reg_acc], "密碼":[hash_password(reg_pw)]})
                            conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_row], ignore_index=True))
                            st.cache_data.clear()
                            st.success("✅ 註冊成功！請切換到『員工薪資查詢』登入。")
                        except Exception as e:
                            st.error(f"❌ 雲端寫入失敗：{e}")
                    else:
                        st.error("❌ 驗證失敗：姓名或身分證字號不正確。")
        return

    # --- 登入後的邏輯 (保持原有功能，不刪減) ---
    role = st.session_state.auth
    
    if role == 5: # 員工個人
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，歡迎使用天康薪資系統")
        p_pay = df_pay[df_pay['姓名'] == name].copy()
        if not p_pay.empty:
            p_pay = p_pay.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
            p_pay = p_pay.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
            bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            for c in bonus_list + ['基本薪資合計', '勞健保自負額']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
            p_pay['實領金額'] = (p_pay['基本薪資合計'] + p_pay[bonus_list].sum(axis=1)) - p_pay['勞健保自負額']
            st.dataframe(p_pay[["月份", "店別", "基本薪資合計"] + bonus_list + ["勞健保自負額", "實領金額", "備註"]])
        else: st.warning("尚未有您的薪資數據。")
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()
    
    else: # 老闆/店長
        shop = st.session_state.shop
        st.sidebar.success(f"📍 管理分店：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()
        
        tabs = st.tabs(["💰 薪資發薪", "👤 員工資料庫", "🏥 勞健保資料", "🔑 帳號清單"])
        
        with tabs[0]: # 薪資作業
            if role == 1:
                with st.sidebar.expander("➕ [管理] 建立新月份"):
                    nm = st.text_input("月份 (如 2026-04)", "2026-04")
                    if st.button("確認寫入"):
                        nr = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":""})
                        conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, nr], ignore_index=True))
                        st.cache_data.clear(); st.rerun()

            months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
            target_m = st.sidebar.selectbox("切換月份", months)
            mask = (df_pay['月份'] == target_m)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            curr = df_pay[mask].copy()
            
            if role == 1:
                curr = curr.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
                curr = curr.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
                bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                for c in bonus_list + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus_list].sum(axis=1)) - curr['勞健保自負額']

            edited = st.data_editor(curr, key="main_edit")
            if st.button("💾 同步存檔薪資"):
                save_df = edited[["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]]
                others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True))
                st.cache_data.clear(); st.success("雲端已更新")
            
            if role == 1:
                if st.button("🚀 匯出網銀 CSV"):
                    f_df = edited.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                    bank = pd.DataFrame({"付款日期":datetime.now().strftime("%Y%m%d"),"轉帳項目":"901","企業編號":"75440263","姓名":f_df["姓名"],"身分證":f_df["身分證"],"帳號":f_df["收款帳號"],"金額":f_df["應付金額"],"附言":"薪資","性質":"02"})
                    st.download_button("📥 下載", bank.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_m}.csv")

        with tabs[1]: # 員工資料
            if role == 1:
                e_emp = st.data_editor(df_emp, num_rows="dynamic")
                if st.button("💾 更新員工主表"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear(); st.success("更新成功")
            else: st.dataframe(df_emp[df_emp['店別'] == shop])
        
        with tabs[2]: # 勞健保
            if role == 1:
                e_ins = st.data_editor(df_ins, num_rows="dynamic")
                if st.button("💾 更新勞健保表"): conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear(); st.success("更新成功")
            else: st.dataframe(df_ins[df_ins['姓名'].isin(df_emp[df_emp['店別']==shop]['姓名'])])

        with tabs[3]: # 帳號管理
            st.dataframe(df_acc)

if __name__ == "__main__":
    main()
