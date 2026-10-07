-- ============================================================
-- ÂM SẮC VIỆT — CỘNG ĐỒNG: bảng xếp hạng chung + đánh giá/bình luận chung
-- Cách chạy: Supabase → SQL Editor → New query → dán TOÀN BỘ file này → Run.
-- Chạy lại nhiều lần vẫn an toàn.
-- ============================================================

-- 1) Bảng xếp hạng chung
create table if not exists public.leaderboard (
  user_id uuid primary key references auth.users(id) on delete cascade,
  name text not null,
  week text not null,
  wk_bac int default 0, wk_trung int default 0, wk_nam int default 0,
  tot_xp int default 0,
  c_bac int default 0, c_trung int default 0, c_nam int default 0,
  updated_at timestamptz default now()
);
alter table public.leaderboard enable row level security;
drop policy if exists "ai cũng xem được bảng xếp hạng" on public.leaderboard;
drop policy if exists "chỉ ghi dòng của mình (thêm)" on public.leaderboard;
drop policy if exists "chỉ ghi dòng của mình (sửa)" on public.leaderboard;
create policy "ai cũng xem được bảng xếp hạng" on public.leaderboard for select using (true);
create policy "chỉ ghi dòng của mình (thêm)" on public.leaderboard for insert with check (auth.uid() = user_id);
create policy "chỉ ghi dòng của mình (sửa)" on public.leaderboard for update using (auth.uid() = user_id);

-- 2) Đánh giá sao cho bài viết (mỗi người 1 đánh giá / bài, được sửa)
create table if not exists public.article_ratings (
  article_id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  stars int not null check (stars between 1 and 5),
  updated_at timestamptz default now(),
  primary key (article_id, user_id)
);
alter table public.article_ratings enable row level security;
drop policy if exists "xem đánh giá" on public.article_ratings;
drop policy if exists "thêm đánh giá của mình" on public.article_ratings;
drop policy if exists "sửa đánh giá của mình" on public.article_ratings;
create policy "xem đánh giá" on public.article_ratings for select using (true);
create policy "thêm đánh giá của mình" on public.article_ratings for insert with check (auth.uid() = user_id);
create policy "sửa đánh giá của mình" on public.article_ratings for update using (auth.uid() = user_id);

-- 3) Bình luận
create table if not exists public.article_comments (
  id bigint generated always as identity primary key,
  article_id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null default 'Người học' check (char_length(name) <= 40),
  text text not null check (char_length(text) between 1 and 800),
  created_at timestamptz default now()
);
create index if not exists article_comments_article_idx on public.article_comments (article_id, created_at desc);
alter table public.article_comments enable row level security;
drop policy if exists "xem bình luận" on public.article_comments;
drop policy if exists "đăng bình luận của mình" on public.article_comments;
drop policy if exists "xoá bình luận của mình" on public.article_comments;
create policy "xem bình luận" on public.article_comments for select using (true);
create policy "đăng bình luận của mình" on public.article_comments for insert with check (auth.uid() = user_id);
create policy "xoá bình luận của mình" on public.article_comments for delete using (auth.uid() = user_id);

-- 4) Thích bình luận
create table if not exists public.comment_likes (
  comment_id bigint not null references public.article_comments(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  article_id text not null,
  primary key (comment_id, user_id)
);
alter table public.comment_likes enable row level security;
drop policy if exists "xem lượt thích" on public.comment_likes;
drop policy if exists "thích bằng tài khoản của mình" on public.comment_likes;
drop policy if exists "bỏ thích của mình" on public.comment_likes;
create policy "xem lượt thích" on public.comment_likes for select using (true);
create policy "thích bằng tài khoản của mình" on public.comment_likes for insert with check (auth.uid() = user_id);
create policy "bỏ thích của mình" on public.comment_likes for delete using (auth.uid() = user_id);
