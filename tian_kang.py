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

# 【核心功能】自動抓取該月份適用的最新勞健保金額
def get_latest_ins(df_ins, target_month):
    if df_ins.empty: return pd.DataFrame(columns=['姓名', '勞健保自負額'])
    # 確保月份格式可以比較 (例如 2026-02)
    df_sorted = df_ins[df_ins['月份'] <= target_month].sort_values(by=['姓名', '月份'], ascending=[True, False])
    # 針對每個人，抓取月份最大(最新)的那一筆
    return df_sorted.drop_duplicates(subset=['姓名'], keep='first')[['姓名', '勞健保自負額']]

def main():
    st.title("🚀 天康連鎖藥局 - 勞健保紀錄與薪資系統")
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
        st.error("❌ 雲端連線忙碌，請稍候再重新載入。")
        st.stop()

    # --- 登入控制系統 ---
    if 'auth' not in st.session_state:
        mode = st.radio("系統入口", ["員工查詢", "管理端登入", "新員工註冊"], horizontal=True)
        if mode == "員工查詢":
            acc = st.text_input("帳號")
            pw = st.text_input("密碼", type="password")
            if st.button("登入查詢"):
                match = df_acc[(df_acc['帳號'] == acc) & (df_acc['密碼'] == hash_password(pw))]
                if not match.empty:
                    st.session_state.auth, st.session_state.user_name = 5, match.iloc[0]['姓名']
                    st.rerun()
                else: st.error("帳號或密碼錯誤")
        elif mode == "管理端登入":
            admin = st.text_input("管理帳號 (boss, mgr_xx, 或 acct)")
            if st.button("進入系統"):
                if admin == "boss": st.session_state.auth, st.session_state.shop = 1, "ALL"
                elif admin == "acct": st.session_state.auth, st.session_state.shop = 4, "ACCOUNTING"
                elif admin.startswith("mgr_"): st.session_state.auth, st.session_state.shop = 3, re.findall(r'\d+', admin)[0].zfill(2)
                else: st.error("權限不足")
                st.rerun()
        elif mode == "新員工註冊":
            with st.form("reg_form"):
                reg_name, reg_id = st.text_input("姓名"), st.text_input("身分證字號")
                reg_acc, reg_pw = st.text_input("設定帳號"), st.text_input("設定密碼", type="password")
                if st.form_submit_button("完成註冊"):
                    if not df_emp[(df_emp['姓名']==reg_name) & (df_emp['身分證']==reg_id)].empty:
                        new_u = pd.DataFrame({"姓名":[reg_name], "身分證":[reg_id], "帳號":[reg_acc], "密碼":[hash_password(reg_pw)]})
                        conn.update(worksheet=ACC_SHEET, data=pd.concat([df_acc, new_u], ignore_index=True))
                        st.cache_data.clear(); st.success("註冊成功！")
                    else: st.error("資料不符")
        return

    role = st.session_state.auth
    shop = st.session_state.shop

    # --- 權限畫面分流 ---
    if role == 5:
        # 員工視角 (自動抓取該員工當時適用的勞健保)
        name = st.session_state.user_name
        st.subheader(f"👋 {name}，個人薪資明細")
        p_pay = df_pay[df_pay['姓名'] == name].copy()
        if not p_pay.empty:
            p_pay = p_pay.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
            # 員工視角的勞健保需要逐月比對最新紀錄 (此處簡化為顯示計算時的快照)
            bonus_list = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
            st.dataframe(p_pay)
        if st.sidebar.button("登出"): del st.session_state['auth']; st.rerun()

    else:
        st.sidebar.success(f"📍 權限：{shop}")
        if st.sidebar.button("登出系統"): del st.session_state['auth']; st.rerun()

        # 會計權限 (Role 4)：專注於維護歷史紀錄
        if role == 4:
            t_acct = st.tabs(["🏥 勞健保歷史維護", "👤 員工名單"])
            with t_acct[0]:
                st.subheader("🏥 勞健保紀錄維護 (保留所有調整紀錄)")
                st.info("💡 提示：若員工勞健保調整，請『新增一列』並設定『生效月份』，勿直接覆蓋舊資料。")
                edited_ins = st.data_editor(df_ins, num_rows="dynamic", key="ins_log_editor")
                if st.button("💾 同步勞健保紀錄至雲端"):
                    conn.update(worksheet=INS_SHEET, data=edited_ins)
                    st.cache_data.clear(); st.success("歷史紀錄已更新！")
            with t_acct[1]:
                st.dataframe(df_emp[["店別", "姓名"]])

        # 老闆與店長權限 (Role 1 & 3)
        else:
            tabs = st.tabs(["💰 薪資發薪", "👤 員工資料", "🏥 勞健保歷史", "🔑 帳號清單"])
            
            with tabs[0]:
                if role == 1:
                    with st.sidebar.expander("➕ [管理] 建立新月份"):
                        nm = st.text_input("新月份", "2026-04")
                        if st.button("寫入雲端"):
                            new_r = pd.DataFrame({"月份":[nm]*len(df_emp), "店別":df_emp["店別"], "姓名":df_emp["姓名"], "職務加給":0, "加班津貼":0, "店毛利成長獎金":0, "推廣獎金":0, "輔具推廣獎金":0, "慢籤成長獎金":0, "備註":""})
                            conn.update(worksheet=PAY_SHEET, data=pd.concat([df_pay, new_r], ignore_index=True)); st.cache_data.clear(); st.rerun()

                target_m = st.sidebar.selectbox("月份", sorted(df_pay['月份'].unique().tolist(), reverse=True))
                mask = (df_pay['月份'] == target_m)
                if role == 3: mask = mask & (df_pay['店別'] == shop)
                curr = df_pay[mask].copy()

                if role == 1:
                    # 【核心邏輯優化】只抓取該月份適用的最新勞健保
                    latest_ins_for_calc = get_latest_ins(df_ins, target_m)
                    
                    curr = curr.merge(df_emp[['姓名','基本薪資合計']], on='姓名', how='left')
                    curr = curr.merge(latest_ins_for_calc, on='姓名', how='left')
                    
                    bonus = ['職務加給', '加班津貼', '店毛利成長獎金', '推廣獎金', '輔具推廣獎金', '慢籤成長獎金']
                    for c in bonus + ['基本薪資合計', '勞健保自負額']: curr[c] = pd.to_numeric(curr[c], errors='coerce').fillna(0)
                    curr['應付金額'] = (curr['基本薪資合計'] + curr[bonus].sum(axis=1)) - curr['勞健保自負額']

                edited = st.data_editor(curr, key="boss_pay_edit")
                if st.button("💾 同步薪資存檔"):
                    save_df = edited[["月份", "店別", "姓名", "職務加給", "加班津貼", "店毛利成長獎金", "推廣獎金", "輔具推廣獎金", "慢籤成長獎金", "備註"]]
                    others = df_pay[~((df_pay['月份']==target_m) & (df_pay['店別'] == (shop if role==3 else df_pay['店別'])))]
                    conn.update(worksheet=PAY_SHEET, data=pd.concat([others, save_df], ignore_index=True)); st.cache_data.clear(); st.success("薪資已更新")

                if role == 1:
                    if st.button("🚀 匯出網銀 CSV"):
                        f_df = edited.merge(df_emp[['姓名', '身分證', '收款帳號']], on='姓名', how='left')
                        bank = pd.DataFrame({"日期":datetime.now().strftime("%Y%m%d"),"項目":"901","編號":"75440263","姓名":f_df["姓名"],"身分證":f_df["身分證"],"帳號":f_df["收款帳號"],"金額":f_df["應付金額"],"附言":"薪資","性質":"02"})
                        st.download_button("📥 下載", bank.to_csv(index=False).encode('utf-8-sig'), f"Bank_{target_m}.csv")

            with tabs[1]:
                if role == 1:
                    e_emp = st.data_editor(df_emp, num_rows="dynamic")
                    if st.button("💾 更新員工主表"): conn.update(worksheet=EMP_SHEET, data=e_emp); st.cache_data.clear(); st.success("更新成功")
                else: st.dataframe(df_emp[df_emp['店別'] == shop])
            
            with tabs[2]: # 勞健保歷史紀錄 (對老闆也是唯讀或編輯歷史)
                st.subheader("🏥 勞健保所有異動紀錄")
                st.dataframe(df_ins.sort_values(by=['姓名', '月份'], ascending=[True, False]))

            with tabs[3]: # 帳號管理
                st.dataframe(df_acc)

if __name__ == "__main__":
    main()
