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
ACC_SHEET = "user_accounts" # 存放員工帳號密碼的分頁

st.set_page_config(page_title="天康藥局雲端管理系統", layout="wide")

# 加密工具：保護員工密碼
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
    st.title("🚀 天康連鎖藥局 - 全方位雲端薪資系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    # 讀取四大資料表
    df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl="0"))
    df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl="0"))
    df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl="0"))
    df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl="0"))

    # --- 登入控制 ---
    if 'auth' not in st.session_state:
        st.subheader("🔐 請先登入系統")
        mode = st.radio("身分選擇", ["員工查詢", "管理端登入", "員工首度註冊"])
        
        if mode == "員工查詢":
            acc = st.text_input("帳號")
            pw = st.text_input("密碼", type="password")
            if st.button("登入查詢"):
                hashed_pw = hash_password(pw)
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hashed_pw)]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("帳號或密碼有誤")

        elif mode == "管理端登入":
            admin_user = st.text_input("管理帳號 (如 boss 或 mgr_04)")
            if st.button("進入後台"):
                if admin_user == "boss":
                    st.session_state.auth, st.session_state.shop = 1, "ALL"
                    st.rerun()
                elif admin_user.startswith("mgr_"):
                    shop_id = re.findall(r'\d+', admin_user)
                    st.session_state.auth, st.session_state.shop = 3, shop_id[0].zfill(2) if shop_id else "00"
                    st.rerun()
                else: st.error("無權限帳號")

        elif mode == "員工首度註冊":
            st.info("驗證身分後即可自訂帳密")
            reg_name = st.text_input("姓名")
            reg_id = st.text_input("身分證字號")
            reg_acc = st.text_input("設定帳號")
            reg_pw = st.text_input("設定密碼", type="password")
            if st.button("完成註冊"):
                # 嚴格驗證是否為公司員工
                if not df_emp[(df_emp['姓名'] == reg_name) & (df_emp['身分證'] == reg_id)].empty:
                    new_acc = pd.DataFrame({"姓名":[reg_name], "身分證":[reg_id], "帳號":[reg_acc], "密碼":[hash_password(reg_pw)]})
                    conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_acc], ignore_index=True))
                    st.success("註冊成功！請切換至『員工查詢』登入。")
                else: st.error("驗證失敗：姓名或身分證與資料庫不符。")
        return

    # --- 登入後畫面 ---
    role = st.session_state.auth

    # 【員工視角 (Role 5)】
    if role == 5:
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，您好！以下是您的薪資明細：")
        p_pay = df_pay[df_pay['姓名'] == name].copy()
        if not p_pay.empty:
            p_pay = p_pay.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
            p_pay = p_pay.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
            bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            for c in bonus_list + ['基本薪資合計', '勞健保自負額']: p_pay[c] = pd.to_numeric(p_pay[c], errors='coerce').fillna(0)
            p_pay['實領金額'] = (p_pay['基本薪資合計'] + p_pay[bonus_list].sum(axis=1)) - p_pay['勞健保自負額']
            st.dataframe(p_pay[["月份", "店別", "基本薪資合計"] + bonus_list + ["勞健保自負額", "實領金額", "備註"]])
        else: st.warning("尚未有您的薪資紀錄。")
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    # 【管理員視角 (Role 1 & 3)】
    else:
        shop = st.session_state.shop
        st.sidebar.success(f"📍 身分：{'總公司' if role==1 else f'分店店長 ({shop})'}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        tabs = st.tabs(["💰 薪資作業", "👤 員工資料", "🏥 勞健保明細", "🔑 帳密管理"])
        
        # --- Tab 1: 薪資作業 ---
        with tabs[0]:
            if role == 1:
                with st.sidebar.expander("➕ 建立新月份"):
                    new_m = st.text_input("新月份 (如 2026-04)", "2026-04")
                    if st.button("生成並寫入雲端"):
                        new_rows = pd.DataFrame({"月份":[new_m]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":""})
                        conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_rows], ignore_index=True))
                        st.success("建立成功"); st.rerun()

            months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
            target_m = st.sidebar.selectbox("月份", months)
            mask = (df_pay['月份'] == target_m)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            curr = df_pay[mask].copy()
            
            # 計算展示 (老闆看應付金額)
            if role == 1:
                curr = curr.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
                curr = curr.merge(df_ins[['姓名','勞健保自負額']], on='姓名', how='left')
                bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                for c in bonus_list + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus_list].sum(axis=1)) - curr['勞健保自負額']

            cols = curr.columns if role == 1 else ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
            edited = st.data_editor(curr[cols], num_rows="dynamic", key="p_edit")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("💾 同步薪資存檔"):
                    save_df = edited[["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]]
                    others = df_pay[~((df_pay['月份'] == target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True))
                    st.success("薪資已更新")

            if role == 1:
                with col_b:
                    if st.button("🚀 匯出銀行 CSV"):
                        f_df = edited.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank = pd.DataFrame({"付款日期":datetime.now().strftime("%Y%m%d"), "轉帳項目":"901", "企業編號":"75440263", "員工姓名":f_df["姓名"], "身分證字號":f_df["身分證"], "收款帳號":f_df["收款帳號"], "交易金額":f_df["應付金額"], "附言":"薪資", "付款性質":"02"})
                        st.download_button("📥 下載", bank.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_m}.csv")

        # --- Tab 2 & 3 & 4: 資料更新 ---
        with tabs[1]:
            if role == 1:
                e_emp = st.data_editor(df_emp, num_rows="dynamic")
                if st.button("💾 同步員工資料"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.success("已更新")
            else: st.dataframe(df_emp[df_emp['店別'] == shop])
        
        with tabs[2]:
            if role == 1:
                e_ins = st.data_editor(df_ins, num_rows="dynamic")
                if st.button("💾 同步勞健保"): conn.update(worksheet=INS_SHEET, data=e_ins); st.success("已更新")
            else: st.dataframe(df_ins[df_ins['姓名'].isin(df_emp[df_emp['店別']==shop]['姓名'])])

        with tabs[3]:
            st.subheader("🔑 員工帳號管理")
            st.dataframe(df_acc)

if __name__ == "__main__":
    main()
