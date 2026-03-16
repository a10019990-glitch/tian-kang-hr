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
    df = df.rename(columns=mapping)
    if "店別" in df.columns:
        df["店別"] = df["店別"].apply(lambda x: re.findall(r'\d+', str(x))[0].zfill(2) if re.findall(r'\d+', str(x)) else str(x).strip())
    return df

# 【核心功能】自動抓取計算月份適用的最新勞健保
def get_latest_ins(df_ins, target_month):
    if df_ins.empty: return pd.DataFrame(columns=['姓名', '勞健保自負額'])
    df_sorted = df_ins[df_ins['月份'] <= target_month].sort_values(by=['姓名', '月份'], ascending=[True, False])
    return df_sorted.drop_duplicates(subset=['姓名'], keep='first')[['姓名', '勞健保自負額']]

def main():
    st.title("🚀 天康連鎖藥局 - 全方位管理系統")
    conn = st.connection("gsheets", type=GSheetsConnection)

    if st.sidebar.button("🔄 重新載入雲端資料"):
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
        st.error("❌ 雲端連線忙碌中，請稍候再重試。")
        st.stop()

    # --- 登入控制 (現在所有模式都要求帳密) ---
    if 'auth' not in st.session_state:
        mode = st.radio("入口選擇", ["員工專區", "管理端後台", "新員工註冊"], horizontal=True)
        
        if mode == "員工專區":
            acc = st.text_input("帳號")
            pw = st.text_input("密碼", type="password")
            if st.button("登入"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("❌ 帳號或密碼錯誤")

        elif mode == "管理端後台":
            adm_acc = st.text_input("管理帳號")
            adm_pw = st.text_input("管理密碼", type="password")
            if st.button("驗證進入"):
                # 從 user_accounts 驗證管理員身分
                match = df_acc[(df_acc['帳號'] == adm_acc) & (df_acc['密碼'] == hash_password(adm_pw))]
                if not match.empty:
                    if adm_acc == "boss":
                        st.session_state.auth, st.session_state.shop = 1, "ALL"
                    elif adm_acc == "acct":
                        st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                    elif adm_acc.startswith("mgr_"):
                        st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', adm_acc)[0].zfill(2)
                    else:
                        st.error("❌ 此帳號不具備管理權限"); st.stop()
                    st.rerun()
                else: st.error("❌ 管理密碼或帳號錯誤")

        elif mode == "新員工註冊":
            with st.form("reg_form"):
                reg_name, reg_id = st.text_input("姓名"), st.text_input("身分證")
                reg_acc, reg_pw = st.text_input("自訂帳號"), st.text_input("自訂密碼", type="password")
                if st.form_submit_button("確認註冊"):
                    # 特殊處理：老闆與會計註冊不需要比對身分證
                    is_admin_reg = reg_acc in ["boss", "acct"] or reg_acc.startswith("mgr_")
                    is_valid_emp = not df_emp[(df_emp['姓名']==reg_name) & (df_emp['身分證']==reg_id)].empty
                    
                    if is_admin_reg or is_valid_emp:
                        new_u = pd.DataFrame({"姓名":[reg_name], "身分證":[reg_id], "帳號":[reg_acc], "密碼":[hash_password(reg_pw)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("✅ 註冊成功！請切換至登入模式。")
                    else: st.error("❌ 驗證失敗：資料庫中查無此員工資訊")
        return

    # --- 登入後的邏輯 (保留所有計算與分級功能) ---
    role = st.session_state.auth
    shop = st.session_state.shop

    if role == 5:
        # 員工視角
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，個人薪資明細")
        p_pay = df_pay[df_pay['姓名'] == name].copy()
        # ... (略過員工顯示細節，維持上一版邏輯)
        st.dataframe(p_pay)
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else:
        st.sidebar.success(f"📍 當前權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        if role == 4: # 會計專屬
            t_acct = st.tabs(["🏥 勞健保歷史維護", "👤 員工對照清單"])
            with t_acct[0]:
                st.subheader("🏥 勞健保紀錄管理")
                edited_ins = st.data_editor(df_ins, num_rows="dynamic")
                if st.button("💾 同步勞健保紀錄"):
                    conn.update(worksheet=INS_SHEET, data=edited_ins)
                    st.cache_data.clear(); st.success("會計資料已同步！")
            with t_acct[1]: st.dataframe(df_emp[["店別", "姓名"]])

        else: # 老闆與店長
            tabs = st.tabs(["💰 薪資發薪作業", "👤 員工資料庫", "🏥 勞健保異動紀錄", "🔑 帳號密碼管理"])
            
            with tabs[0]: # 薪資與發薪 (核心計算不刪減)
                if role == 1:
                    with st.sidebar.expander("➕ [管理] 建立新月份"):
                        nm = st.text_input("新月份 (如 2026-04)", "2026-04")
                        if st.button("執行建立"):
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":""})
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()

                months = sorted(df_pay['月份'].unique().tolist(), reverse=True) if not df_pay.empty else ["無資料"]
                target_m = st.sidebar.selectbox("月份切換", months)
                mask = (df_pay['月份'] == target_m)
                if role == 3: mask = mask & (df_pay['店別'] == shop)
                curr = df_pay[mask].copy()

                if role == 1: # 老闆視角：自動計算應付金額
                    latest_ins = get_latest_ins(df_ins, target_m)
                    curr = curr.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
                    curr = curr.merge(latest_ins, on='姓名', how='left')
                    bonus = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus].sum(axis=1)) - curr['勞健保自負額']

                edited = st.data_editor(curr, key="pay_edit")
                if st.button("💾 同步薪資存檔"):
                    save_df = edited[["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]]
                    others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("雲端已更新")

                if role == 1: # 銀行匯出
                    if st.button("🚀 匯出網銀 CSV"):
                        f_df = edited.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank = pd.DataFrame({"日期":datetime.now().strftime("%Y%m%d"),"項目":"901","編號":"75440263","姓名":f_df["姓名"],"身分證":f_df["身分證"],"帳號":f_df["收款帳號"],"金額":f_df["應付金額"],"附言":"薪資","性質":"02"})
                        st.download_button("📥 下載", bank.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_m}.csv")

            with tabs[1]: # 員工資料同步
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 同步員工主表"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear(); st.success("更新成功")
                else: st.dataframe(df_emp[df_emp['店別'] == shop])
            
            with tabs[2]: # 勞健保紀錄
                st.dataframe(df_ins.sort_values(by=['姓名', '月份'], ascending=[True, False]))

            with tabs[3]: # 帳號管理
                st.subheader("🔑 系統帳號清單 (含管理員)")
                st.dataframe(df_acc)

if __name__ == "__main__":
    main()
