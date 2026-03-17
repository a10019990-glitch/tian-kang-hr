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

def robust_clean(df, expected_cols=None):
    if df is None or df.empty: 
        return pd.DataFrame(columns=expected_cols if expected_cols else [])
    
    # 清理標題
    df.columns = [str(c).strip().replace('\n', '') for c in df.columns]
    mapping = {c: "店別" for c in df.columns if "店別" in c or "店號" in c}
    mapping.update({c: "姓名" for c in df.columns if "姓名" in c})
    mapping.update({c: "月份" for c in df.columns if "月份" in c or "生效月份" in c})
    mapping.update({c: "勞健保自負額" for c in df.columns if "自負額" in c or "勞健保" in c})
    mapping.update({c: "身分證" for c in df.columns if "身分證" in c or "字號" in c})
    mapping.update({c: "單位" for c in df.columns if "單位" in c or "類別" in c})
    mapping.update({c: "基本薪資合計" for c in df.columns if "基本薪資" in c})
    
    df = df.rename(columns=mapping)
    
    # 強制補齊預期欄位，避免 KeyError
    if expected_cols:
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "" # 補空白

    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

# 銀行檔生成工具
def generate_bank_csv(df_source, df_employee, target_m):
    f_df = df_source.merge(df_employee[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
    bank = pd.DataFrame({
        "付款日期": datetime.now().strftime("%Y%m%d"),
        "轉帳項目": "901", "企業編號": "75440263",
        "員工姓名": f_df["姓名"], "身分證字號": f_df["身分證"],
        "收款帳號": f_df["收款帳號"], "交易金額": f_df["應付金額"],
        "附言": "薪資", "付款性質": "02"
    })
    return bank.to_csv(index=False).encode('utf-8-sig')

def main():
    st.title("🚀 天康連鎖藥局 - 雙單位發薪管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 刷新雲端資料"):
        st.cache_data.clear()
        st.rerun()

    DEFAULT_TTL = 300 

    # --- 讀取資料 (加上預期欄位保護) ---
    try:
        df_emp = robust_clean(conn.read(worksheet=EMP_SHEET, ttl=DEFAULT_TTL), 
                              expected_cols=['姓名', '店別', '身分證', '收款帳號', '基本薪資合計', '單位'])
        df_pay = robust_clean(conn.read(worksheet=PAY_SHEET, ttl=DEFAULT_TTL),
                              expected_cols=['月份', '店別', '姓名', '備註'])
        df_ins = robust_clean(conn.read(worksheet=INS_SHEET, ttl=DEFAULT_TTL),
                              expected_cols=['姓名', '月份', '勞健保自負額'])
        df_acc = robust_clean(conn.read(worksheet=ACC_SHEET, ttl=DEFAULT_TTL),
                              expected_cols=['姓名', '帳號', '密碼'])
    except Exception as e:
        st.error(f"❌ 雲端連線失敗或分頁不存在: {e}"); st.stop()

    # --- 登入系統 ---
    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["員工專區", "管理端登入", "新帳號註冊"], horizontal=True)
        if mode == "員工專區":
            acc, pw = st.text_input("帳號"), st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("帳號或密碼錯誤")
        elif mode == "管理端登入":
            adm_acc, adm_pw = st.text_input("管理帳號"), st.text_input("管理密碼", type="password")
            if st.button("驗證進入"):
                match = df_acc[(df_acc['帳號'] == adm_acc) & (df_acc['密碼'] == hash_password(adm_pw))]
                if not match.empty:
                    if adm_acc == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif adm_acc == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif adm_acc.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', adm_acc)[0].zfill(2)
                    st.rerun()
                else: st.error("身分驗證失敗")
        elif mode == "新帳號註冊":
            with st.form("reg"):
                n, i, a, p = st.text_input("姓名"), st.text_input("身分證"), st.text_input("帳號"), st.text_input("密碼", type="password")
                if st.form_submit_button("註冊"):
                    if a in ["boss", "acct"] or a.startswith("mgr_") or not df_emp[(df_emp['姓名']==n) & (df_emp['身分證']==i)].empty:
                        new_u = pd.DataFrame({"姓名":[n], "身分證":[i], "帳號":[a], "密碼":[hash_password(p)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("註冊成功")
                    else: st.error("查無員工資訊")
        return

    # --- 權限分流 ---
    role = st.session_state.auth
    shop = st.session_state.shop

    if role == 5:
        # 員工視角
        st.subheader(f"👋 {st.session_state.user_name}，個人薪資明細")
        st.dataframe(df_pay[df_pay['姓名'] == st.session_state.user_name])
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()
    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

        tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保紀錄", "🔑 帳號管理"])
        
        with tabs[0]:
            if role == 1:
                with st.sidebar.expander("➕ 建立新月份"):
                    nm = st.text_input("新月份", "2026-04")
                    if st.button("執行建立"):
                        # 備註繼承邏輯
                        latest_rem = df_pay.sort_values(['姓名','月份'], ascending=[True,False]).drop_duplicates('姓名')[['姓名','備註']] if not df_pay.empty else pd.DataFrame(columns=['姓名','備註'])
                        df_t = df_emp.merge(latest_rem, on='姓名', how='left')
                        new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":df_t["備註"].fillna("")})
                        conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()

            target_m = st.sidebar.selectbox("月份", sorted(df_pay['月份'].unique().tolist(), reverse=True))
            mask = (df_pay['月份'] == target_m)
            if role == 3: mask = mask & (df_pay['店別'] == shop)
            curr = df_pay[mask].copy()

            if role == 1:
                # 抓取最新勞健保並整合單位資訊
                df_s = df_ins[df_ins['月份'] <= target_m].sort_values(['姓名', '月份'], ascending=[True, False])
                l_ins = df_s.drop_duplicates('姓名')[['姓名', '勞健保自負額']]
                
                # 這裡增加對 df_emp 的欄位存在性檢查
                emp_cols = [c for c in ['姓名','基本薪資合計', '單位'] if c in df_emp.columns]
                curr = curr.merge(df_emp[emp_cols], on='姓名', how='left')
                curr = curr.merge(l_ins, on='姓名', how='left')
                
                bonus = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                for c in bonus + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus].sum(axis=1)) - curr['勞健保自負額']

            edited = st.data_editor(curr, key="p_edit")
            
            if st.button("💾 同步薪資存檔"):
                save_cols = ["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]
                save_df = edited[[c for c in save_cols if c in edited.columns]]
                others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("已存檔")

            if role == 1:
                st.markdown("---")
                st.subheader("🚀 雙單位網銀發薪匯出")
                c1, c2 = st.columns(2)
                with c1:
                    df_ph = edited[edited.get('單位', '') == '藥局']
                    if not df_ph.empty: st.download_button("📥 下載【藥局】網銀檔", generate_bank_csv(df_ph, df_emp, target_m), f"Pharmacy_{target_m}.csv")
                    else: st.info("藥局目前無資料")
                with c2:
                    df_cm = edited[edited.get('單位', '') == '個管師']
                    if not df_cm.empty: st.download_button("📥 下載【個管師】網銀檔", generate_bank_csv(df_cm, df_emp, target_m), f"CaseManager_{target_m}.csv")
                    else: st.info("個管師目前無資料")

        with tabs[1]:
            if role == 1:
                e_emp = st.data_editor(df_emp, num_rows="dynamic")
                if st.button("💾 同步員工資料"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear()
            else: st.dataframe(df_emp[df_emp['店別'] == shop])

if __name__ == "__main__":
    main()
