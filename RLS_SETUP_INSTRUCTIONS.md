# Row Level Security (RLS) Setup Instructions

## 🚨 **Problem:**
The RLS policies for `arxiv_papers`, `arxiv_categories`, and `summary_papers` tables were overwritten, breaking access control.

## ✅ **Solution:**
Three SQL scripts have been created to restore and maintain proper RLS policies.

---

## 📋 **Step 1: Restore RLS Policies (IMMEDIATE)**

Run this script in your **Supabase SQL Editor** to restore RLS immediately:

```sql
-- Copy and paste the contents of restore_rls_policies.sql
```

**File**: `restore_rls_policies.sql`  
**Purpose**: Restores RLS policies for all existing tables

---

## 🔧 **Step 2: Verify RLS is Working**

Run this script to check that RLS policies are correctly applied:

```sql
-- Copy and paste the contents of verify_rls.sql
```

**File**: `verify_rls.sql`  
**Purpose**: Verifies RLS status, policies, and permissions

**Expected Results**:
- ✅ `rls_enabled = true` for both tables
- ✅ 4 policies per table (read, insert, update, delete)
- ✅ Proper permissions for `anon`, `authenticated`, and `service_role`

---

## 🛡️ **Step 3: Prevent Future Overwrites**

### Updated Table Creation Scripts
- ✅ `create_table.sql` - Now includes RLS policies
- ✅ `create_summary_papers_table.sql` - Now includes RLS policies

### **Important**: Always use these updated scripts for future deployments!

---

## 🔑 **RLS Policy Summary**

### **Permissions Structure**:

| Role | `arxiv_papers` | `summary_papers` | Views |
|------|----------------|------------------|-------|
| **anon** | SELECT, INSERT, UPDATE | SELECT, INSERT, UPDATE | SELECT |
| **authenticated** | SELECT, INSERT, UPDATE, DELETE | SELECT, INSERT, UPDATE, DELETE | SELECT |
| **service_role** | ALL | ALL | ALL |

### **Policy Details**:
1. **Read Access**: ✅ Anyone (including anonymous users)
2. **Insert/Update**: ✅ ETL operations with anon key
3. **Delete**: ❌ Only authenticated users and service role
4. **Admin Operations**: ✅ Service role has full access

---

## 🧪 **Testing RLS**

### Test with your current anon key:
```sql
-- These should work:
SELECT COUNT(*) FROM arxiv_papers;
SELECT COUNT(*) FROM summary_papers;
SELECT COUNT(*) FROM v_papers_needing_summaries;

-- This should work (ETL operations):
-- INSERT/UPDATE statements from your ETL
```

### Test restrictions:
```sql
-- This should be restricted for anon:
-- DELETE FROM arxiv_papers WHERE id = 1;
```

---

## 🚫 **How to Prevent Future Overwrites**

### **DO THIS**:
- ✅ Always use the updated SQL scripts (`create_table.sql`, `create_summary_papers_table.sql`)
- ✅ Run `verify_rls.sql` after any schema changes
- ✅ Include RLS policies in all new table creation scripts

### **DON'T DO THIS**:
- ❌ Run `DROP TABLE CASCADE` without restoring RLS
- ❌ Use old SQL scripts without RLS policies
- ❌ Disable RLS without proper access controls

---

## 🔄 **If RLS Gets Overwritten Again**

1. **Immediate fix**: Run `restore_rls_policies.sql`
2. **Verify**: Run `verify_rls.sql`
3. **Test**: Check ETL operations still work
4. **Document**: Note what caused the override

---

## 📞 **Need Help?**

If the ETL stops working after applying RLS:

1. Check error messages for permission issues
2. Run `verify_rls.sql` to diagnose
3. Ensure your anon key has proper permissions
4. Check if any new tables need RLS policies

**Remember**: RLS protects your data while allowing your ETL to function properly! 🛡️ 