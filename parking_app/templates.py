from __future__ import annotations

from html import escape
from typing import Optional


def logo_markup() -> str:
    return """
    <div class="brand-image">
      <img src="/static/assets/branding/logo.png" alt="LeasingMarkt" class="brand-logo" onerror="this.parentElement.classList.add('missing')">
      <div class="brand-fallback">LeasingMarkt</div>
    </div>
    """


def avatar_markup(name: str, profile_image: str, cls: str = "avatar") -> str:
    initials = "".join(part[:1] for part in name.split()[:2]).upper() or "LM"
    if profile_image and "." in profile_image:
        return f'<img src="/static/assets/profiles/{escape(profile_image)}" alt="{escape(name)}" class="{cls} avatar-image">'
    label = (profile_image or initials)[:2].upper()
    return f'<div class="{cls}">{escape(label)}</div>'


def html_page(title: str, body: str, current_user=None, flash: Optional[str] = None, *, show_header: bool = True, profile_href: str = "/?tab=profile") -> str:
    flash_html = f'<div class="flash">{escape(flash)}</div>' if flash else ""
    header = ""
    if show_header:
        profile_block = ""
        if current_user:
            profile_block = f"""
            <a class="profile-pill profile-link" href="{escape(profile_href)}">
              {avatar_markup(current_user['name'], current_user['profile_image'])}
              <div>
                <div class="profile-name">{escape(current_user['name'])}</div>
                <div class="profile-meta">{escape(current_user['email'])}</div>
              </div>
            </a>
            """
        header = f"""
        <header class="topbar glass">
          <div class="brand-area">
            {logo_markup()}
            <div class="header-copy">
              <p class="eyebrow">Office parking</p>
              <h1>{escape(title)}</h1>
            </div>
          </div>
          {profile_block}
        </header>
        """
    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <link rel="stylesheet" href="/static/style.css">
    <script defer src="/static/app.js"></script>
  </head>
  <body>
    <div class="backdrop"></div>
    <div class="app-shell">
      {header}
      {flash_html}
      {body}
    </div>
  </body>
</html>
"""


def login_page(mode: str = "login", flash: Optional[str] = None) -> str:
    body = f"""
    <main class="auth-layout auth-simple">
      <section class="glass auth-card">
        <div class="auth-brand">{logo_markup()}</div>
        <h1>Reserve office parking with less friction.</h1>
        <p class="lead">Plan the week, reserve a spot, and keep your parking history in one place.</p>
        <div class="auth-switch">
          <a class="auth-tab {'active' if mode == 'login' else ''}" href="/login">Log in</a>
          <a class="auth-tab {'active' if mode == 'register' else ''}" href="/register">Register</a>
        </div>
        <div class="auth-panel {'hidden' if mode != 'login' else ''}">
          <form method="post" action="/login" class="stack-form">
            <label>Email<input type="email" name="email" required></label>
            <label>Password<input type="password" name="password" required></label>
            <button type="submit">Open parking tool</button>
          </form>
        </div>
        <div class="auth-panel {'hidden' if mode != 'register' else ''}">
          <form method="post" action="/register" class="stack-form">
            <label>Full name<input type="text" name="name" required></label>
            <label>Email<input type="email" name="email" required></label>
            <label>Confirm email<input type="email" name="confirm_email" required></label>
            <label>Password<input type="password" name="password" minlength="8" required></label>
            <label>Confirm password<input type="password" name="confirm_password" minlength="8" required></label>
            <button type="submit">Create account</button>
          </form>
        </div>
      </section>
    </main>
    """
    return html_page("Parking Login", body, flash=flash, show_header=False)


def dashboard_page(
    *,
    current_user,
    week_label,
    prev_week_href,
    next_week_href,
    week_cells,
    selected_date,
    selected_day_summary,
    booked_spots_count,
    selected_booking,
    waitlist_entry,
    spot_map,
    day_booking_rows,
    compatible_spots,
    own_bookings,
    flash: Optional[str],
    active_tab: str,
    booking_mode: str,
    show_waitlist: bool,
    hidden_spots,
    current_week: str,
    garage_video_available: bool,
    formatted_selected_date: str,
) -> str:
    admin_link = '<a class="auth-tab admin-tab" href="/admin">Admin</a>' if current_user["role"] == "admin" else ""
    tabs = {
        "booking": "active" if active_tab == "booking" else "",
        "history": "active" if active_tab == "history" else "",
        "guide": "active" if active_tab == "guide" else "",
    }
    week_html = "".join(
        f"""
        <a class="week-cell {'selected' if cell['selected'] else ''} {'dimmed' if cell['dimmed'] else ''}" href="/?week={cell['week']}&date={cell['date']}&tab={active_tab}">
          <span class="week-day">{escape(cell['weekday'])}</span>
          <span class="week-number">{escape(cell['day_number'])}</span>
          <span class="week-date">{escape(cell['date_label'])}</span>
          <span class="week-rail"><span class="week-fill" style="width:{escape(cell['fill_width'])}"></span></span>
          <span class="week-state">{escape(cell['state'])}</span>
          <span class="week-meta">{escape(cell['meta'])}</span>
        </a>
        """
        for cell in week_cells
    )
    spot_options = '<option value="">Auto-assign the best available spot</option>' + "".join(
        f'<option value="{spot["id"]}">{escape(spot["label"])}{" · " + escape(spot["notes"]) if spot["notes"] else ""}</option>'
        for spot in compatible_spots
    )
    hidden_notes = "".join(f"<li>{escape(spot['label'])}: max {escape(str(spot['max_height_cm']))} cm vehicle height</li>" for spot in hidden_spots)
    garage_html = "".join(
        f"""
        <div class="garage-spot spot-{escape(spot['status'])}">
          <div class="garage-spot-head">
            <span class="garage-spot-label">{escape(spot['label'])}</span>
            {avatar_markup(spot['booked_by_name'], spot['booked_by_image'], cls='mini-avatar') if spot['booked_by_name'] else ''}
          </div>
          <div class="garage-spot-type">{escape(spot['kind'])}</div>
          <div class="garage-spot-state">{escape(spot['state'])}</div>
          {"<div class='garage-spot-detail'>" + escape(spot['detail']) + "</div>" if spot['detail'] else ""}
        </div>
        """
        for spot in spot_map
    )
    day_booking_html = "".join(
        f"""
        <div class="booking-person">
          {avatar_markup(row['booking_name'], row['profile_image'], cls='mini-avatar')}
          <div>
            <div class="booking-person-name">{escape(row['booking_name'])}</div>
            <div class="booking-person-meta">{escape(row['spot_label'])} · {escape(row['booking_type'])}</div>
          </div>
        </div>
        """
        for row in day_booking_rows
    )
    history_rows = "".join(
        f"""
        <tr>
          <td>{escape(row['formatted_date'])}</td>
          <td>{escape(row['spot_label'])}</td>
          <td>{escape(row['booking_for_label'])}</td>
          <td>{escape(row['duration_label'])}</td>
          <td>{escape(row['status_label'])}</td>
          <td>{row['action_html']}</td>
        </tr>
        """
        for row in own_bookings
    )
    booking_panel = f"""
    <section class="booking-overview">
      <section class="glass panel-card">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Booking</p>
            <h3>{escape(formatted_selected_date)}</h3>
          </div>
          <p class="panel-summary">{escape(selected_day_summary)}</p>
        </div>
        <div class="booking-mode-tabs">
          <a class="auth-tab {'active' if booking_mode == 'self' else ''}" href="/?week={escape(current_week)}&date={escape(selected_date)}&tab=booking&booking_mode=self">Book for yourself</a>
          <a class="auth-tab {'active' if booking_mode == 'guest' else ''}" href="/?week={escape(current_week)}&date={escape(selected_date)}&tab=booking&booking_mode=guest">Book for someone else</a>
        </div>
        <form method="post" action="/bookings" class="stack-form form-spacing">
          <input type="hidden" name="booking_date" value="{escape(selected_date)}">
          <input type="hidden" name="selected_date" value="{escape(selected_date)}">
          <input type="hidden" name="week" value="{escape(current_week)}">
          <input type="hidden" name="booking_mode" value="{escape(booking_mode)}">
          <label>
            Vehicle size
            <select name="vehicle_size">
              <option value="">No size limit</option>
              <option value="small">Small car under 150 cm</option>
              <option value="medium">Mid-size car up to 165 cm</option>
              <option value="large">Large car above 165 cm</option>
            </select>
          </label>
          <label>
            Parking spot
            <select name="spot_id">{spot_options}</select>
          </label>
          <div class="guest-fields {'hidden-guest-fields' if booking_mode != 'guest' else ''}">
            <label>
              Guest name
              <input type="text" name="guest_name" placeholder="Required for guest bookings">
            </label>
            <label>
              Guest email
              <input type="email" name="guest_email" placeholder="Optional">
            </label>
          </div>
          <label class="checkbox-row">
            <input type="checkbox" name="policy_acknowledged" value="yes" required>
            <span>I need this parking space for a full office day and accept the parking rules.</span>
          </label>
          <button type="submit">Reserve parking</button>
        </form>
        {"<div class='info-box'><strong>Unavailable double-parkers</strong><ul class='rule-list'>" + hidden_notes + "</ul></div>" if hidden_notes else ""}
        {render_waitlist(show_waitlist, waitlist_entry, selected_date, current_week)}
      </section>
      <section class="glass panel-card garage-below">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Day overview</p>
            <h3>{escape(str(booked_spots_count))} spots reserved</h3>
          </div>
        </div>
        <div class="booking-people-list">{day_booking_html or "<div class='guide-placeholder'>No bookings for this day yet.</div>"}</div>
        <div class="garage-grid">{garage_html}</div>
      </section>
    </section>
    """
    history_panel = f"""
    <section class="glass panel-card">
      <p class="eyebrow">History</p>
      <h3>Your booked spots</h3>
      <table>
        <thead><tr><th>Date</th><th>Spot</th><th>Reserved for</th><th>Duration</th><th>Status</th><th></th></tr></thead>
        <tbody>{history_rows or '<tr><td colspan="6">No bookings yet.</td></tr>'}</tbody>
      </table>
    </section>
    """
    guide_panel = f"""
    <section class="glass panel-card">
      <p class="eyebrow">Guide</p>
      <h3>How to reach the parking spaces</h3>
      {"<video class='guide-video' controls src='/static/assets/guide/garage-guide.mp4'></video>" if garage_video_available else "<div class='guide-placeholder'>No guide video is available yet.</div>"}
      <p class="lead compact">P5 is the lower double-parker. P6 is the upper double-parker. Check the vehicle height limit before you book.</p>
    </section>
    """
    profile_panel = f"""
    <section class="glass panel-card">
      <p class="eyebrow">Profile</p>
      <h3>Update your details</h3>
      <form method="post" action="/profile/update" class="stack-form">
        <input type="hidden" name="week" value="{escape(current_week)}">
        <input type="hidden" name="date" value="{escape(selected_date)}">
        <label>Full name<input type="text" name="name" value="{escape(current_user['name'])}" required></label>
        <label>Email<input type="email" name="email" value="{escape(current_user['email'])}" required></label>
        <label>Profile image or initials<input type="text" name="profile_image" value="{escape(current_user['profile_image'])}" placeholder="Optional"></label>
        <button type="submit">Save profile</button>
      </form>
      <form method="post" action="/logout" class="stack-form compact-form">
        <button class="secondary-button" type="submit">Log out</button>
      </form>
    </section>
    """
    panel = {"booking": booking_panel, "history": history_panel, "guide": guide_panel, "profile": profile_panel}.get(active_tab, booking_panel)
    body = f"""
    <main class="dashboard-stack">
      <section class="glass week-panel">
        <div class="week-header">
          <div>
            <p class="eyebrow">This week</p>
            <h2 class="week-range">{escape(week_label)}</h2>
          </div>
          <div class="week-nav">
            <a class="nav-button" href="{escape(prev_week_href)}">Previous</a>
            <a class="nav-button" href="{escape(next_week_href)}">Next</a>
          </div>
        </div>
        <div class="week-grid">{week_html}</div>
      </section>
      <section class="content-stack">
        <div class="tab-row">
          <a class="auth-tab {tabs['booking']}" href="/?week={escape(current_week)}&date={escape(selected_date)}&tab=booking">Booking</a>
          <a class="auth-tab {tabs['history']}" href="/?week={escape(current_week)}&date={escape(selected_date)}&tab=history">History</a>
          <a class="auth-tab {tabs['guide']}" href="/?week={escape(current_week)}&date={escape(selected_date)}&tab=guide">Guide</a>
          {admin_link}
        </div>
        {panel}
      </section>
    </main>
    """
    profile_href = f"/?week={escape(current_week)}&date={escape(selected_date)}&tab=profile"
    return html_page("Parking Tool", body, current_user=current_user, flash=flash, profile_href=profile_href)


def render_waitlist(show_waitlist: bool, waitlist_entry, selected_date: str, current_week: str) -> str:
    if not show_waitlist:
        return ""
    if waitlist_entry:
        return f"""
        <section class="info-box">
          <p>You are already on the waitlist for this day.</p>
          <form method="post" action="/waitlist/{waitlist_entry['id']}/leave" class="stack-form compact-form">
            <input type="hidden" name="selected_date" value="{escape(selected_date)}">
            <input type="hidden" name="week" value="{escape(current_week)}">
            <button class="secondary-button" type="submit">Leave waitlist</button>
          </form>
        </section>
        """
    return f"""
    <section class="info-box">
      <p>All spots are taken for this day. You can join the waitlist instead.</p>
      <form method="post" action="/waitlist" class="stack-form compact-form">
        <input type="hidden" name="booking_date" value="{escape(selected_date)}">
        <input type="hidden" name="selected_date" value="{escape(selected_date)}">
        <input type="hidden" name="week" value="{escape(current_week)}">
        <button class="secondary-button" type="submit">Join waitlist</button>
      </form>
    </section>
    """


def admin_page(*, current_user, rules, spots, users, bookings, waitlist_entries, overrides, notifications, audit_entries, flash: Optional[str] = None) -> str:
    summary_cards = f"""
    <div class="admin-summary-grid">
      <section class="glass panel-card summary-card">
        <p class="eyebrow">People</p>
        <h3>{len(users)}</h3>
        <p class="lead compact">Total accounts in the system.</p>
      </section>
      <section class="glass panel-card summary-card">
        <p class="eyebrow">Active bookings</p>
        <h3>{len(bookings)}</h3>
        <p class="lead compact">Current reserved parking spots.</p>
      </section>
      <section class="glass panel-card summary-card">
        <p class="eyebrow">Waitlist</p>
        <h3>{len(waitlist_entries)}</h3>
        <p class="lead compact">Employees currently waiting for a spot.</p>
      </section>
      <section class="glass panel-card summary-card">
        <p class="eyebrow">Parking spots</p>
        <h3>{len(spots)}</h3>
        <p class="lead compact">Managed spaces in the tool.</p>
      </section>
    </div>
    """
    user_rows = "".join(
        f"""
        <tr>
          <td>{avatar_markup(row['name'], row['profile_image'], cls='mini-avatar')}</td>
          <td>{escape(row['name'])}</td>
          <td>{escape(row['email'])}</td>
          <td>{escape(row['role'])}</td>
          <td>
            <form method="post" action="/admin/users/{row['id']}/role" class="inline-form">
              <input type="hidden" name="role" value="{'employee' if row['role'] == 'admin' else 'admin'}">
              <button class="ghost-button" type="submit">{'Make employee' if row['role'] == 'admin' else 'Make admin'}</button>
            </form>
            <form method="post" action="/admin/users/{row['id']}/remove" class="inline-form">
              <button class="ghost-button" type="submit">Remove</button>
            </form>
          </td>
        </tr>
        """
        for row in users
    )
    spot_rows = "".join(
        f"<tr><td>{escape(row['label'])}</td><td>{escape('Lower double-parker' if row['kind'] == 'elevator-bottom' else 'Upper double-parker' if row['kind'] == 'elevator-top' else 'Standard')}</td><td>{escape(str(row['max_height_cm']) if row['max_height_cm'] else 'No limit')}</td></tr>"
        for row in spots
    )
    booking_rows = "".join(
        f"<tr><td>{escape(row['booking_date'])}</td><td>{escape(row['spot_label'])}</td><td>{escape(row['booking_name'])}</td></tr>"
        for row in bookings[:8]
    )
    body = f"""
    <main class="dashboard-stack">
      <section class="glass week-panel admin-hero">
        <div class="week-header">
          <div>
            <p class="eyebrow">Admin</p>
            <h2 class="week-range">Parking operations</h2>
            <p class="lead compact">Manage people, rules, and daily occupancy from one place.</p>
          </div>
          <div class="week-nav">
            <a class="nav-button" href="/?tab=booking">Back to booking view</a>
          </div>
        </div>
      </section>
      {summary_cards}
      <section class="admin-layout">
      <section class="glass panel-card">
        <p class="eyebrow">People</p>
        <h3>Invite or update employees</h3>
        <form method="post" action="/admin/invite" class="stack-form">
          <label>Full name<input type="text" name="name" required></label>
          <label>Email<input type="email" name="email" required></label>
          <label>Temporary password<input type="text" name="password" placeholder="parking123"></label>
          <button type="submit">Create employee</button>
        </form>
        <table>
          <thead><tr><th></th><th>Name</th><th>Email</th><th>Role</th><th>Actions</th></tr></thead>
          <tbody>{user_rows}</tbody>
        </table>
      </section>
      <section class="glass panel-card">
        <p class="eyebrow">Rules</p>
        <h3>Booking limits</h3>
        <form method="post" action="/admin/rules" class="stack-form">
          <label>Max days per week<input type="number" name="max_days_per_week" min="1" max="5" value="{rules['max_days_per_week']}"></label>
          <label>Max consecutive days<input type="number" name="max_consecutive_days" min="1" max="5" value="{rules['max_consecutive_days']}"></label>
          <label>Booking window in days<input type="number" name="booking_window_days" min="1" max="7" value="{rules['booking_window_days']}"></label>
          <button type="submit">Save rules</button>
        </form>
      </section>
      <section class="glass panel-card">
        <p class="eyebrow">Garage inventory</p>
        <h3>Managed parking spots</h3>
        <table><thead><tr><th>Spot</th><th>Type</th><th>Height limit</th></tr></thead><tbody>{spot_rows}</tbody></table>
      </section>
      <section class="glass panel-card">
        <p class="eyebrow">Live bookings</p>
        <h3>Today and upcoming reservations</h3>
        <table><thead><tr><th>Date</th><th>Spot</th><th>Reserved for</th></tr></thead><tbody>{booking_rows or '<tr><td colspan="3">No active bookings.</td></tr>'}</tbody></table>
      </section>
      </section>
    </main>
    """
    return html_page("Admin", body, current_user=current_user, flash=flash)
