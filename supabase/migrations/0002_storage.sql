-- ==========================================================
-- Storage bucket for per-user resume PDFs
-- ==========================================================

insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', false)
on conflict (id) do nothing;

-- Objects are stored as "{user_id}/resume.pdf" so ownership can be checked
-- either via the "owner" column (set automatically by supabase-py when the
-- uploading user's JWT is used) or by matching the path prefix, which is
-- what we rely on since uploads go through the service role on the backend.

create policy "Users read their own resume"
  on storage.objects for select
  using (
    bucket_id = 'resumes'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "Users upload their own resume"
  on storage.objects for insert
  with check (
    bucket_id = 'resumes'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "Users update their own resume"
  on storage.objects for update
  using (
    bucket_id = 'resumes'
    and auth.uid()::text = (storage.foldername(name))[1]
  );

create policy "Users delete their own resume"
  on storage.objects for delete
  using (
    bucket_id = 'resumes'
    and auth.uid()::text = (storage.foldername(name))[1]
  );
