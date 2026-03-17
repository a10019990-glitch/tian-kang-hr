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

def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def robust_clean(df):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c or "生效月份" in c})
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    mapping.update({c: "身分證" for c in df.columns if "身分證" in c or "字號" in c})
    mapping.update({c: "單位" for c in df.columns if "單位" in c or "類別" in c})
    
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

# 銀行檔生成工具函數
def generate_bank_csv(df_source, df_employee, target_m):
    # 勾稽資料
    f_df = df_source.merge(df_employee[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"),
        "轉帳項目": "901",
        "企業編號": "75440263",
        "員工姓名": f_df["姓名"],
        "身分證字號": f_df["身分證"],
        "收款帳號": f_df["收款帳號"],
        "交易金額": f_df["應付金額"],
        "附言": "薪資",
        "付款性質": "02"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 - 雙單位發薪管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear()
        st.rerun()

    DEFAULT_TTL = 300 

    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=DEFAULT_TTL))
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=DEFAULT_TTL))
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=DEFAULT_TTL))
        try:
            df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=DEFAULT_TTL))
        except:
            df_acc = pd.DataFrame(columns=["姓名", "身分證", "帳號", "密碼"])
    except Exception as e:
        st.error("❌ 雲端忙碌中，請稍候重試。"); st.stop()

    # --- 登入系統 ---
    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["員工專區", "管理後台", "註冊"], horizontal=True)
        if mode == "員工專區":
            acc, pw = st.text_input("帳號"), st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("錯誤")
        elif mode == "管理後台":
            adm_acc, adm_pw = st.text_input("管理帳號"), st.text_input("管理密碼", type="password")
            if st.button("登入後台"):
                match = df_acc[(df_acc['帳號'] == adm_acc) & (df_acc['密碼'] == hash_password(adm_pw))]
                if not match.empty:
                    if adm_acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif adm_acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif adm_acc.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', adm_acc)[0].zfill(2)
                    st.rerun()
                else: st.error("驗證失敗")
        elif mode == "註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("註冊"):
                    if a in ["boss", "acct"] or a.startswith("mgr_") or not df_emp[(df_emp['姓名']==n) & (df_emp['身分證']==i)].empty:
                        new_u = pd.DataFrame({"姓名":[n], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("註冊成功")
        return

    # --- 管理與員工邏輯 ---
    role = st.session_state.auth
    shop = st.session_state.shop

    if role == 5:
        st.subheader(f"👋 {st.session_state.user_name}，您的薪資明細")
        p_pay = df_pay[df_pay['姓名'] == st.session_state.user_name]
        st.dataframe(p_pay)
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()
    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        if role == 4: # 會計
            tabs = st.tabs(["🏥 勞健保維護", "👤 員工清單"])
            with tabs[0]:
                e_ins = st.data_editor(df_ins, num_rows="dynamic")
                if st.button("💾 同步勞健保"): conn.update(worksheet=INS_SHEET, data=e_ins); st.cache_data.clear()
        else: # 老闆與店長
            tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄", "🔑 帳號管理"])
            
            with tabs[0]:
                # 建立新月份 (保留備註繼承功能)
                if role == 1:
                    with st.sidebar.expander("➕ [管理] 建立新月份"):
                        nm = st.text_input("新月份", "2026-04")
                        if st.button("執行建立"):
                            latest_remarks = df_pay.sort_values(by=['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名',keep='first')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                            df_temp = df_emp.merge(latest_remarks, on='姓名', how='left')
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":df_temp["備註"].fillna("")})
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()

                target_m = st.sidebar.selectbox("月份切換", sorted(df_pay['月份'].unique().tolist(), reverse=True))
                mask = (df_pay['月份'] == target_m)
                if role == 3: mask = mask & (df_pay['店別'] == shop)
                curr = df_pay[mask].copy()

                # 老闆視角：連動計算與雙按鈕匯出
                if role == 1:
                    # 抓取最新勞健保
                    df_sorted = df_ins[df_ins['月份'] <= target_m].sort_values(by=['姓名', '月份'], ascending=[True, False])
                    l_ins = df_sorted.drop_duplicates(subset=['姓名'], keep='first')[['姓名', '勞健保自負額']]
                    
                    # 整合資料
                    curr = curr.merge(df_emp[['姓名','基本薪資合計', '單位']], on='姓名', how='left')
                    curr = curr.merge(l_ins, on='姓名', how='left')
                    
                    bonus = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus].sum(axis=1)) - curr['勞健保自負額']

                edited = st.data_editor(curr, key="pay_edit")
                
                # 存檔與匯出按鈕區
                if st.button("💾 同步存檔"):
                    save_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
                    save_df = edited[save_cols]
                    others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("已更新")

                if role == 1:
                    st.markdown("---")
                    st.subheader("🚀 網銀發薪匯出 (分單位)")
                    c1, c2 = st.columns(2)
                    
                    # 按鈕 1: 藥局
                    with c1:
                        df_pharmacy = edited[edited['單位'] == '藥局']
                        if not df_pharmacy.empty:
                            csv_pharmacy = generate_bank_csv(df_pharmacy, df_emp, target_m)
                            st.download_button("📥 下載【藥局】網銀檔", csv_pharmacy, f"Bank_Pharmacy_{target_m}.csv", use_container_width=True)
                        else: st.write("藥局無資料")

                    # 按鈕 2: 個管師
                    with c2:
                        df_manager = edited[edited['單位'] == '個管師']
                        if not df_manager.empty:
                            csv_manager = generate_bank_csv(df_manager, df_emp, target_m)
                            st.download_button("📥 下載【個管師】網銀檔", csv_manager, f"Bank_CaseManager_{target_m}.csv", use_container_width=True)
                        else: st.write("個管師無資料")

            with tabs[1]:
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 同步員工主表"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
                else: st.dataframe(df_emp[df_emp['店別'] == shop])

if __name__ == "__main__":
    main()
