"""Streamlit UI for BillSplit Agent."""

import base64
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from src.agents import MockToolContext
from src.tools import OcrError, calculate_bill_split, extract_receipt_text, parse_bill_text, remember_split_preferences
from src.utils.formatting import money
from src.utils.bill_store import get_saved_bill, list_saved_bills, load_receipt_upload, save_bill_record, save_receipt_upload
from src.utils.team_store import load_team_members, save_team_members


st.set_page_config(page_title="BillSplit Agent", layout="wide")


def main() -> None:
    _init_state()
    _apply_styles()

    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.title("BillSplit Agent")
        st.caption("A guided bill-splitting assistant")
    with header_right:
        if st.button("Start over", use_container_width=True):
            _reset_session()
            st.rerun()

    _agent_timeline()

    split_tab, saved_tab, team_tab = st.tabs(["Split Receipt", "Saved Bills", "Team Members"])

    with team_tab:
        _team_member_editor()

    with saved_tab:
        _saved_bills_page()

    with split_tab:
        work, agent = st.columns([2, 1])
        with work:
            bill_text = _receipt_input()
        with agent:
            _agent_briefing(bill_text)
            _receipt_preview()

        if not bill_text.strip():
            return
        _reset_receipt_flow_if_text_changed(bill_text)

        receipt = st.session_state.loaded_receipt or _with_stable_item_ids(parse_bill_text(bill_text, st.session_state.context))
        with work:
            people = _receipt_people_selector()

        if not people:
            return

        with work:
            receipt = _bill_editor(receipt, people)
            st.session_state.current_receipt = receipt
            st.session_state.current_people = people

        if not receipt["items"]:
            st.warning("No bill items were detected. Check the receipt text or add clearer item lines.")
            return

        with work:
            assignments = st.session_state.current_assignments
            _render_unassigned_people(people, assignments)
            st.session_state.current_assignments = assignments
            assignment_signature = _assignment_signature(assignments)
            if st.session_state.last_assignment_signature != assignment_signature:
                st.session_state.last_assignment_signature = assignment_signature
                st.session_state.plan = None
            assignments_complete = _assignments_complete(receipt, assignments)
            if not st.session_state.receipt_review_complete:
                st.info("Confirm each item and who ate it before asking the agent to calculate the split.")
            if st.button(
                "Ask agent to split bill",
                type="primary",
                use_container_width=True,
                disabled=not st.session_state.receipt_review_complete or not assignments_complete,
            ):
                remember_split_preferences(people, st.session_state.context)
                plan = calculate_bill_split(receipt, people, assignments, st.session_state.context)
                st.session_state.plan = plan

        if st.session_state.plan:
            with work:
                _render_results(st.session_state.plan, key_prefix="current")
                _save_current_bill_button()


def _init_state() -> None:
    if "context" not in st.session_state:
        st.session_state.context = MockToolContext()
    if "receipt_text" not in st.session_state:
        st.session_state.receipt_text = ""
    if "receipt_upload" not in st.session_state:
        st.session_state.receipt_upload = None
    if "last_receipt_text" not in st.session_state:
        st.session_state.last_receipt_text = ""
    if "plan" not in st.session_state:
        st.session_state.plan = None
    if "team_members" not in st.session_state:
        st.session_state.team_members = load_team_members()
    if "loaded_receipt" not in st.session_state:
        st.session_state.loaded_receipt = None
    if "current_receipt" not in st.session_state:
        st.session_state.current_receipt = None
    if "current_people" not in st.session_state:
        st.session_state.current_people = []
    if "current_assignments" not in st.session_state:
        st.session_state.current_assignments = {}
    if "assignment_item_index" not in st.session_state:
        st.session_state.assignment_item_index = 0
    if "receipt_item_index" not in st.session_state:
        st.session_state.receipt_item_index = 0
    if "receipt_review_complete" not in st.session_state:
        st.session_state.receipt_review_complete = False
    if "manual_item_count" not in st.session_state:
        st.session_state.manual_item_count = 0
    if "removed_item_ids" not in st.session_state:
        st.session_state.removed_item_ids = set()
    if "confirmed_receipt_items" not in st.session_state:
        st.session_state.confirmed_receipt_items = {}
    if "receipt_item_values" not in st.session_state:
        st.session_state.receipt_item_values = {}
    if "editing_bill_id" not in st.session_state:
        st.session_state.editing_bill_id = None
    if "selected_saved_bill_id" not in st.session_state:
        st.session_state.selected_saved_bill_id = None
    if "last_bill_signature" not in st.session_state:
        st.session_state.last_bill_signature = None
    if "last_assignment_signature" not in st.session_state:
        st.session_state.last_assignment_signature = None


def _reset_session() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    _init_state()


def _reset_receipt_flow_if_text_changed(bill_text: str) -> None:
    if st.session_state.last_receipt_text == bill_text:
        return
    st.session_state.last_receipt_text = bill_text
    st.session_state.loaded_receipt = None
    st.session_state.current_receipt = None
    st.session_state.current_assignments = {}
    st.session_state.assignment_item_index = 0
    st.session_state.receipt_item_index = 0
    st.session_state.receipt_review_complete = False
    st.session_state.manual_item_count = 0
    st.session_state.removed_item_ids = set()
    st.session_state.confirmed_receipt_items = {}
    st.session_state.receipt_item_values = {}
    st.session_state.plan = None
    st.session_state.editing_bill_id = None
    if not st.session_state.get("receipt_upload"):
        st.session_state.receipt_upload = None
    _clear_bill_widget_state()
    st.session_state.assignment_item_index = 0
    st.session_state.receipt_item_index = 0
    st.session_state.receipt_review_complete = False
    st.session_state.manual_item_count = 0
    st.session_state.removed_item_ids = set()
    st.session_state.confirmed_receipt_items = {}
    st.session_state.receipt_item_values = {}


def _apply_styles() -> None:
    st.markdown(
        """
        <style>
        .agent-step {
            border-left: 3px solid #2563eb;
            padding: 0.35rem 0 0.35rem 0.75rem;
            margin-bottom: 0.35rem;
            color: #334155;
        }
        .agent-step-done {
            border-color: #16a34a;
            color: #14532d;
        }
        .agent-note {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 0.9rem;
            margin-top: 0.45rem;
        }
        .unassigned-person {
            display: inline-block;
            color: #991b1b;
            background: #fee2e2;
            border: 1px solid #fecaca;
            border-radius: 6px;
            padding: 0.12rem 0.45rem;
            margin: 0.1rem;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _agent_timeline() -> None:
    has_receipt = bool(st.session_state.receipt_text.strip())
    has_plan = st.session_state.plan is not None
    steps = [
        ("Read receipt", has_receipt),
        ("Extract items and charges", has_receipt),
        ("Ask who ate what", has_receipt),
        ("Calculate fair split", has_plan),
    ]

    columns = st.columns(len(steps))
    for column, (label, done) in zip(columns, steps):
        css_class = "agent-step agent-step-done" if done else "agent-step"
        status = "Done" if done else "Waiting"
        column.markdown(f"<div class='{css_class}'><strong>{label}</strong><br>{status}</div>", unsafe_allow_html=True)


def _agent_briefing(bill_text: str) -> None:
    st.subheader("Agent")
    if not bill_text.strip():
        with st.chat_message("assistant"):
            st.write("Send me a receipt image or paste the text. I will read it, find the dishes, then ask who shared each item.")
        return

    with st.chat_message("assistant"):
        st.write("I found receipt text. Review the items I extracted, then tell me the people and who ate each dish.")
    if st.session_state.plan:
        with st.chat_message("assistant"):
            st.write("The split is ready. I divided service charge and tax by each person's item subtotal.")


def _receipt_input() -> str:
    st.subheader("Receipt")
    tab_upload, tab_paste = st.tabs(["Upload", "Paste"])

    with tab_upload:
        uploaded = st.file_uploader("Receipt image or PDF", type=["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "pdf"])
        if uploaded is not None and st.button("Ask agent to read receipt", use_container_width=True):
            suffix = Path(uploaded.name).suffix
            upload_bytes = uploaded.getvalue()
            st.session_state.receipt_upload = {
                "name": uploaded.name,
                "type": uploaded.type or _mime_type_from_suffix(suffix),
                "bytes": upload_bytes,
            }
            with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(upload_bytes)
                temp_path = Path(temp_file.name)
            try:
                with st.spinner("Reading receipt..."):
                    st.session_state.receipt_text = extract_receipt_text(temp_path)
                    st.session_state.plan = None
                st.success("Receipt text extracted.")
            except OcrError as error:
                st.error(str(error))

    with tab_paste:
        st.session_state.receipt_text = st.text_area(
            "Receipt text",
            value=st.session_state.receipt_text,
            height=240,
            placeholder="Paste receipt text here if OCR is not available.",
        )

    return st.session_state.receipt_text


def _receipt_preview() -> None:
    upload = st.session_state.get("receipt_upload")
    if not upload:
        return

    st.subheader("Receipt Image")
    file_type = upload.get("type") or ""
    file_bytes = upload.get("bytes") or b""
    if file_type.startswith("image/"):
        st.image(file_bytes, caption=upload.get("name") or "Uploaded receipt", width="stretch")
        return

    if file_type == "application/pdf":
        encoded = base64.b64encode(file_bytes).decode("ascii")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{encoded}" width="100%" height="650"></iframe>',
            unsafe_allow_html=True,
        )
        return

    st.caption(upload.get("name") or "Uploaded receipt")
    st.info("Preview is available for image and PDF uploads.")


def _mime_type_from_suffix(suffix: str) -> str:
    image_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }
    if suffix.lower() == ".pdf":
        return "application/pdf"
    return image_types.get(suffix.lower(), "application/octet-stream")


def _bill_editor(receipt: dict, people: list[str]) -> dict:
    st.subheader("Confirm Receipt Items")

    top = st.columns([2, 1, 1, 1, 1])
    with top[0]:
        restaurant_name = st.text_input("Restaurant", value=receipt["restaurant_name"] or "")
    with top[1]:
        service_charge = st.number_input("SST / service", min_value=-999.0, value=float(receipt["service_charge"]), step=0.10)
    with top[2]:
        tax = st.number_input("Tax", min_value=0.0, value=float(receipt["tax"]), step=0.10)
    with top[3]:
        receipt_subtotal = st.number_input(
            "Receipt subtotal",
            min_value=0.0,
            value=float(receipt.get("receipt_subtotal") or 0),
            step=0.10,
        )
    with top[4]:
        receipt_total = st.number_input(
            "Receipt total",
            min_value=0.0,
            value=float(receipt.get("receipt_total") or receipt.get("bill_total") or 0),
            step=0.10,
        )
    receipt_subtotal_value = Decimal(str(receipt_subtotal)).quantize(Decimal("0.01")) if receipt_subtotal else None
    receipt_total_value = Decimal(str(receipt_total)).quantize(Decimal("0.01")) if receipt_total else None

    review_items = _receipt_review_items(receipt)
    _sync_assignment_items(review_items)
    _render_receipt_item_review(review_items, people)
    edited_items = _edited_receipt_items(review_items)

    detected_total = sum((item["price"] for item in edited_items), Decimal("0"))
    detected_total += Decimal(str(service_charge)) + Decimal(str(tax))

    _render_bill_cross_check(edited_items, Decimal(str(service_charge)), Decimal(str(tax)), receipt_subtotal_value, receipt_total_value)

    edited_receipt = {
        **receipt,
        "restaurant_name": restaurant_name.strip(),
        "items": edited_items,
        "service_charge": Decimal(str(service_charge)),
        "tax": Decimal(str(tax)),
        "detected_total": detected_total,
        "bill_total": receipt_total_value or detected_total,
        "receipt_subtotal": receipt_subtotal_value,
        "receipt_total": receipt_total_value,
    }
    bill_signature = _bill_signature(edited_receipt)
    if st.session_state.get("last_bill_signature") != bill_signature:
        st.session_state.last_bill_signature = bill_signature
        st.session_state.plan = None
        _prune_removed_item_state({item["id"] for item in edited_items})
    return edited_receipt


def _receipt_review_items(receipt: dict) -> list[dict]:
    removed_item_ids = st.session_state.removed_item_ids
    items = [item for item in receipt["items"] if item["id"] not in removed_item_ids]
    for index in range(st.session_state.manual_item_count):
        item_id = f"manual-{index}"
        if item_id not in removed_item_ids:
            items.append({"id": item_id, "name": "", "price": Decimal("0")})
    if not items:
        st.session_state.receipt_item_index = 0
        return items
    st.session_state.receipt_item_index = min(st.session_state.receipt_item_index, len(items) - 1)
    return items


def _render_receipt_item_review(items: list[dict], people: list[str]) -> None:
    if not items:
        st.warning("No items were detected. Add a missing item to continue.")
        if st.button("Add missing item", type="primary", use_container_width=True):
            st.session_state.manual_item_count += 1
            st.session_state.receipt_item_index = 0
            st.session_state.receipt_review_complete = False
            st.rerun()
        return

    current_index = st.session_state.receipt_item_index
    item = items[current_index]
    st.markdown(f"**Confirm item {current_index + 1} of {len(items)}**")

    cols = st.columns([4, 1])
    with cols[0]:
        st.text_input("Item name", value=_receipt_item_name(item), key=f"item-name-{item['id']}")
    with cols[1]:
        st.number_input(
            "Amount",
            min_value=0.0,
            value=float(_receipt_item_price(item)),
            step=0.10,
            format="%.2f",
            key=f"item-price-{item['id']}",
        )
    st.markdown("**Who ate this item?**")
    current_assignment = _assignment_controls(item, people)

    confirmed_count = _confirmed_receipt_item_count(items)
    st.session_state.receipt_review_complete = confirmed_count == len(items)
    st.progress(confirmed_count / len(items), text=f"{confirmed_count} of {len(items)} items saved")

    if st.button("Remove this item", use_container_width=True):
        _remove_receipt_item(item["id"], len(items))
        st.rerun()

    can_confirm = _receipt_item_is_valid(item) and bool(current_assignment)
    save_label = "Save receipt" if current_index == len(items) - 1 else "Save and next"
    if st.button(save_label, type="primary", use_container_width=True, disabled=not can_confirm):
        _confirm_receipt_item(item, current_assignment)
        st.session_state.receipt_review_complete = _confirmed_receipt_item_count(items) == len(items)
        if current_index < len(items) - 1:
            st.session_state.receipt_item_index = current_index + 1
        elif not st.session_state.receipt_review_complete:
            st.session_state.receipt_item_index = _first_unconfirmed_item_index(items)
        st.rerun()

    nav_cols = st.columns(2)
    with nav_cols[0]:
        if st.button("Previous item", use_container_width=True, disabled=current_index == 0):
            st.session_state.receipt_item_index = max(current_index - 1, 0)
            st.rerun()
    with nav_cols[1]:
        if st.button("Add missing item", use_container_width=True):
            st.session_state.manual_item_count += 1
            st.session_state.receipt_item_index = len(items)
            st.session_state.receipt_review_complete = False
            st.rerun()

    if not st.session_state.receipt_review_complete:
        st.info("Edit the item if needed, choose who ate it, then save to move forward.")


def _edited_receipt_items(items: list[dict]) -> list[dict]:
    edited_items = []
    for item in items:
        name = _receipt_item_name(item).strip()
        price = _receipt_item_price(item)
        if name and price > 0:
            edited_items.append({"id": item["id"], "name": name, "price": price})
    return edited_items


def _receipt_item_is_valid(item: dict) -> bool:
    name = _receipt_item_name(item).strip()
    price = _receipt_item_price(item)
    return bool(name) and price > 0


def _receipt_item_signature(item: dict) -> tuple[str, str]:
    name = _receipt_item_name(item).strip()
    price = _receipt_item_price(item).quantize(Decimal("0.01"))
    return name, str(price)


def _receipt_item_name(item: dict) -> str:
    widget_key = f"item-name-{item['id']}"
    if widget_key in st.session_state:
        return str(st.session_state[widget_key])
    saved = st.session_state.receipt_item_values.get(item["id"], {})
    return str(saved.get("name", item["name"]))


def _receipt_item_price(item: dict) -> Decimal:
    widget_key = f"item-price-{item['id']}"
    if widget_key in st.session_state:
        return Decimal(str(st.session_state[widget_key]))
    saved = st.session_state.receipt_item_values.get(item["id"], {})
    return Decimal(str(saved.get("price", item["price"])))


def _assignment_signature_value(portions: dict[str, Decimal]) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (person, str(Decimal(str(portion)).quantize(Decimal("0.1"))))
            for person, portion in portions.items()
        )
    )


def _receipt_confirmation_value(
    item: dict,
    assignment: dict[str, Decimal],
) -> tuple[tuple[str, str], tuple[tuple[str, str], ...]]:
    return _receipt_item_signature(item), _assignment_signature_value(assignment)


def _confirm_receipt_item(item: dict, assignment: dict[str, Decimal]) -> None:
    st.session_state.receipt_item_values[item["id"]] = {
        "name": _receipt_item_name(item).strip(),
        "price": _receipt_item_price(item),
    }
    st.session_state.current_assignments[item["id"]] = assignment
    st.session_state.confirmed_receipt_items[item["id"]] = _receipt_confirmation_value(item, assignment)


def _receipt_item_is_confirmed(item: dict) -> bool:
    if not _receipt_item_is_valid(item):
        return False
    confirmed = st.session_state.confirmed_receipt_items.get(item["id"])
    if not confirmed:
        return False
    item_signature, assignment_signature = confirmed
    return item_signature == _receipt_item_signature(item) and bool(assignment_signature)


def _confirmed_receipt_item_count(items: list[dict]) -> int:
    return sum(1 for item in items if _receipt_item_is_confirmed(item))


def _first_unconfirmed_item_index(items: list[dict]) -> int:
    for index, item in enumerate(items):
        if not _receipt_item_is_confirmed(item):
            return index
    return max(len(items) - 1, 0)


def _remove_receipt_item(item_id: str, item_count: int) -> None:
    st.session_state.removed_item_ids.add(item_id)
    st.session_state.confirmed_receipt_items.pop(item_id, None)
    st.session_state.receipt_item_values.pop(item_id, None)
    st.session_state.pop(f"item-name-{item_id}", None)
    st.session_state.pop(f"item-price-{item_id}", None)
    st.session_state.current_assignments.pop(item_id, None)
    st.session_state.receipt_item_index = max(0, min(st.session_state.receipt_item_index, item_count - 2))
    st.session_state.receipt_review_complete = False


def _prune_removed_item_state(item_ids: set[str]) -> None:
    st.session_state.current_assignments = {
        item_id: portions
        for item_id, portions in st.session_state.current_assignments.items()
        if item_id in item_ids
    }
    st.session_state.confirmed_receipt_items = {
        item_id: confirmation
        for item_id, confirmation in st.session_state.confirmed_receipt_items.items()
        if item_id in item_ids
    }
    st.session_state.receipt_item_values = {
        item_id: value
        for item_id, value in st.session_state.receipt_item_values.items()
        if item_id in item_ids
    }


def _bill_signature(receipt: dict) -> tuple:
    return (
        receipt.get("restaurant_name"),
        str(receipt.get("service_charge")),
        str(receipt.get("tax")),
        str(receipt.get("receipt_subtotal")),
        str(receipt.get("receipt_total")),
        tuple((item["id"], item["name"], str(item["price"])) for item in receipt.get("items", [])),
    )


def _assignment_signature(assignments: dict[str, dict[str, Decimal]]) -> tuple:
    return tuple(
        sorted(
            (
                item_id,
                tuple(sorted((person, str(portion)) for person, portion in portions.items())),
            )
            for item_id, portions in assignments.items()
        )
    )


def _render_unassigned_people(people: list[str], assignments: dict[str, dict[str, Decimal]]) -> None:
    assigned_people = {
        person
        for portions in assignments.values()
        for person, portion in portions.items()
        if Decimal(str(portion)) > 0
    }
    unassigned = [person for person in people if person not in assigned_people]
    if not unassigned:
        return

    badges = " ".join(
        f"<span class='unassigned-person'>{person}</span>"
        for person in unassigned
    )
    st.markdown(
        f"**No items assigned yet:** {badges}",
        unsafe_allow_html=True,
    )


def _render_bill_cross_check(
    items: list[dict],
    service_charge: Decimal,
    tax: Decimal,
    receipt_subtotal: Decimal | None,
    receipt_total: Decimal | None,
) -> None:
    item_subtotal = sum((item["price"] for item in items), Decimal("0")).quantize(Decimal("0.01"))
    calculated_total = (item_subtotal + service_charge + tax).quantize(Decimal("0.01"))
    st.caption(f"Extracted subtotal: {money(item_subtotal)} | Calculated total: {money(calculated_total)}")

    warnings = []
    if receipt_subtotal is not None and abs(item_subtotal - receipt_subtotal) >= Decimal("0.02"):
        warnings.append(f"Extracted items do not match receipt subtotal. Difference: {money(item_subtotal - receipt_subtotal)}")
    if receipt_total is not None and abs(calculated_total - receipt_total) >= Decimal("0.02"):
        warnings.append(f"Calculated total does not match receipt total. Difference: {money(calculated_total - receipt_total)}")
    for warning in warnings:
        st.warning(warning)


def _team_member_editor() -> None:
    st.subheader("Team Members")
    with st.expander("Manage saved members", expanded=not bool(st.session_state.receipt_text.strip())):
        raw_members = st.text_area(
            "One member per line",
            value="\n".join(st.session_state.team_members),
            height=130,
            key="team-members-text",
        )
        columns = st.columns([1, 1])
        with columns[0]:
            if st.button("Save members", use_container_width=True):
                members = _clean_names(raw_members.splitlines())
                if members:
                    st.session_state.team_members = save_team_members(members)
                    _clear_member_dependent_state()
                    st.success(f"Saved {len(members)} member(s).")
                    st.rerun()
                else:
                    st.warning("Add at least one team member.")
        with columns[1]:
            new_member = st.text_input("Quick add", key="new-team-member")
            if st.button("Add member", use_container_width=True):
                name = " ".join(new_member.split())
                if name and name not in st.session_state.team_members:
                    st.session_state.team_members = save_team_members([*st.session_state.team_members, name])
                    _clear_member_dependent_state()
                    st.rerun()
                elif name:
                    st.info(f"{name} is already saved.")

        if st.session_state.team_members:
            st.caption("Saved: " + ", ".join(st.session_state.team_members))


def _saved_bills_page() -> None:
    st.subheader("Saved Bills")
    bills = list_saved_bills()
    if not bills:
        st.info("No saved bills yet. Calculate a split, then save it from the result section.")
        return

    list_col, detail_col = st.columns([1, 2])
    with list_col:
        for bill in bills:
            restaurant = bill.get("restaurant_name") or "Unknown restaurant"
            date = _format_saved_date(bill.get("updated_at") or bill.get("created_at"))
            if st.button(f"{restaurant}\n{date}", key=f"open-saved-{bill['id']}", use_container_width=True):
                st.session_state.selected_saved_bill_id = bill["id"]

    selected_id = st.session_state.selected_saved_bill_id or bills[0]["id"]
    selected = get_saved_bill(selected_id)
    if not selected:
        return

    with detail_col:
        _render_saved_bill_detail(selected)


def _render_saved_bill_detail(saved: dict) -> None:
    st.markdown(f"### {saved.get('restaurant_name') or 'Unknown restaurant'}")
    st.caption(f"Saved: {_format_saved_date(saved.get('updated_at') or saved.get('created_at'))}")

    plan = saved.get("plan")
    if plan:
        _render_results(_restore_plan_decimals(plan), key_prefix=f"saved-{saved['id']}")
    else:
        receipt = saved.get("receipt", {})
        st.write(f"Receipt total: {money(receipt.get('bill_total') or receipt.get('detected_total') or 0)}")
        st.write(f"People: {', '.join(saved.get('people', []))}")

    if st.button("Edit this bill", key=f"edit-saved-{saved['id']}", type="primary"):
        _load_saved_bill_for_edit(saved)
        st.success("Loaded into Split Receipt. Open the Split Receipt tab to edit and save again.")


def _load_saved_bill_for_edit(saved: dict) -> None:
    receipt = saved.get("receipt") or {}
    st.session_state.loaded_receipt = _restore_receipt_decimals(receipt)
    st.session_state.receipt_text = receipt.get("raw_text", "")
    st.session_state.last_receipt_text = st.session_state.receipt_text
    st.session_state.receipt_upload = load_receipt_upload(saved)
    st.session_state.current_people = saved.get("people", [])
    st.session_state.current_assignments = _restore_assignments(saved.get("assignments", {}))
    st.session_state.plan = _restore_plan_decimals(saved.get("plan"))
    st.session_state.editing_bill_id = saved.get("id")
    st.session_state.receipt_item_index = 0
    st.session_state.receipt_review_complete = True
    st.session_state.manual_item_count = 0
    st.session_state.removed_item_ids = set()
    st.session_state.receipt_item_values = {
        item["id"]: {"name": item["name"], "price": Decimal(str(item["price"]))}
        for item in st.session_state.loaded_receipt.get("items", [])
    }
    st.session_state.confirmed_receipt_items = {
        item["id"]: (
            (item["name"], str(Decimal(str(item["price"])).quantize(Decimal("0.01")))),
            _assignment_signature_value(st.session_state.current_assignments.get(item["id"], {})),
        )
        for item in st.session_state.loaded_receipt.get("items", [])
    }
    _clear_bill_widget_state()
    st.session_state.receipt_review_complete = True


def _save_current_bill_button() -> None:
    label = "Update saved bill" if st.session_state.editing_bill_id else "Save bill"
    if not st.button(label, use_container_width=True):
        return

    receipt = st.session_state.current_receipt
    if not receipt:
        st.warning("No bill details available to save.")
        return

    record = {
        "id": st.session_state.editing_bill_id,
        "restaurant_name": receipt.get("restaurant_name") or "Unknown restaurant",
        "receipt": receipt,
        "people": st.session_state.current_people,
        "assignments": st.session_state.current_assignments,
        "plan": st.session_state.plan,
    }
    saved = save_bill_record(record)
    upload_fields = save_receipt_upload(saved["id"], st.session_state.get("receipt_upload"))
    if upload_fields:
        saved = save_bill_record({**saved, **upload_fields})
    st.session_state.editing_bill_id = saved["id"]
    st.session_state.selected_saved_bill_id = saved["id"]
    st.success("Bill saved.")


def _clear_bill_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if (
            key.startswith("item-name-")
            or key.startswith("item-price-")
            or key.startswith("assign-mode-")
            or key.startswith("assign-people-")
            or key.startswith("portion-")
            or key == "assignment_item_index"
            or key.startswith("receipt-person-")
        ):
            del st.session_state[key]
    st.session_state.last_bill_signature = None
    st.session_state.last_assignment_signature = None


def _restore_receipt_decimals(receipt: dict) -> dict:
    restored = {**receipt}
    restored["items"] = [
        {**item, "price": Decimal(str(item["price"]))}
        for item in receipt.get("items", [])
    ]
    for key in ("service_charge", "tax", "detected_total", "bill_total", "receipt_subtotal", "receipt_total"):
        if restored.get(key) is not None:
            restored[key] = Decimal(str(restored[key]))
    return restored


def _restore_assignments(assignments: dict) -> dict[str, dict[str, Decimal]]:
    return {
        item_id: {person: Decimal(str(portion)) for person, portion in portions.items()}
        for item_id, portions in assignments.items()
    }


def _restore_plan_decimals(plan: dict | None) -> dict | None:
    if not plan:
        return None
    restored = {**plan}
    for key in ("detected_total", "calculated_total", "receipt_total", "receipt_subtotal"):
        if restored.get(key) is not None:
            restored[key] = Decimal(str(restored[key]))
    restored["splits"] = []
    for split in plan.get("splits", []):
        restored_split = {**split}
        for key in ("item_subtotal", "service_charge", "tax", "total"):
            restored_split[key] = Decimal(str(restored_split[key]))
        restored_split["items"] = [
            {
                **item,
                "amount": Decimal(str(item["amount"])),
                "portions": Decimal(str(item.get("portions", "1"))),
            }
            for item in split.get("items", [])
        ]
        restored["splits"].append(restored_split)
    return restored


def _format_saved_date(value: str | None) -> str:
    if not value:
        return "No date"
    return value.replace("T", " ")


def _receipt_people_selector() -> list[str]:
    st.subheader("Agent Question: Who joined this receipt?")
    members = st.session_state.team_members
    if not members:
        st.warning("Add team members before splitting this receipt.")
        return []

    st.caption("Select the people who joined this receipt.")
    columns = st.columns(min(len(members), 4))
    selected = []
    saved_people = set(st.session_state.current_people or [])
    for index, member in enumerate(members):
        with columns[index % len(columns)]:
            checked = st.checkbox(member, value=member in saved_people, key=f"receipt-person-{member}")
            if checked:
                selected.append(member)

    if not selected:
        st.warning("Select at least one diner for this receipt.")
    return selected


def _clean_names(values: list[str]) -> list[str]:
    cleaned = []
    for value in values:
        name = " ".join(value.split())
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def _clear_member_dependent_state() -> None:
    for key in list(st.session_state.keys()):
        if (
            key.startswith("assign-")
            or key.startswith("assign-mode-")
            or key.startswith("assign-people-")
            or key.startswith("portion-")
            or key == "assignment_item_index"
            or key == "receipt-people"
            or key.startswith("receipt-person-")
        ):
            del st.session_state[key]


def _assignment_editor(receipt: dict, people: list[str]) -> dict[str, dict[str, Decimal]]:
    st.subheader("Agent Question: Who ate what?")

    items = receipt["items"]
    _sync_assignment_items(items)
    _quick_assignment_box(receipt, people)

    current_index = min(st.session_state.assignment_item_index, len(items) - 1)
    st.session_state.assignment_item_index = current_index
    item = items[current_index]

    st.markdown(f"**Item {current_index + 1} of {len(items)}**")
    st.write(f"{item['name']} - {money(item['price'])}")

    assignments = dict(st.session_state.current_assignments)
    assignments[item["id"]] = _assignment_controls(item, people)
    st.session_state.current_assignments = assignments

    completed_count = sum(1 for bill_item in items if assignments.get(bill_item["id"]))
    st.progress(completed_count / len(items), text=f"{completed_count} of {len(items)} items assigned")

    _assignment_navigation(items, assignments)
    return assignments


def _sync_assignment_items(items: list[dict]) -> None:
    item_ids = {item["id"] for item in items}
    st.session_state.current_assignments = {
        item_id: portions
        for item_id, portions in st.session_state.current_assignments.items()
        if item_id in item_ids
    }
    if st.session_state.assignment_item_index >= len(items):
        st.session_state.assignment_item_index = max(len(items) - 1, 0)


def _assignment_controls(item: dict, people: list[str]) -> dict[str, Decimal]:
    saved_portions = st.session_state.current_assignments.get(item["id"], {})
    saved_people = [person for person in saved_portions if person in people]
    if saved_people and set(saved_people) == set(people):
        default_mode_index = 0
    else:
        default_mode_index = 1
    mode = st.radio(
        "Who had this item?",
        options=["All", "Choose people"],
        horizontal=True,
        index=default_mode_index,
        key=f"assign-mode-{item['id']}",
    )

    if mode == "All":
        selected_people = people[:]
    else:
        selected_people = _people_checkbox_selector(item, people)

    return _portion_inputs(item, selected_people)


def _assignment_navigation(items: list[dict], assignments: dict[str, dict[str, Decimal]]) -> None:
    previous_col, next_col = st.columns(2)
    current_index = st.session_state.assignment_item_index
    current_item = items[current_index]
    current_assigned = bool(assignments.get(current_item["id"]))

    with previous_col:
        if st.button("Previous item", use_container_width=True, disabled=current_index == 0):
            st.session_state.assignment_item_index = max(current_index - 1, 0)
            st.rerun()

    with next_col:
        is_last_item = current_index == len(items) - 1
        next_label = "Finish assignments" if is_last_item else "Next item"
        if st.button(next_label, type="primary", use_container_width=True, disabled=not current_assigned):
            st.session_state.assignment_item_index = min(current_index + 1, len(items) - 1)
            st.rerun()

    if not current_assigned:
        st.caption("Select one or more members to continue.")


def _assignments_complete(receipt: dict, assignments: dict[str, dict[str, Decimal]]) -> bool:
    return bool(receipt.get("items")) and all(assignments.get(item["id"]) for item in receipt["items"])


def _people_checkbox_selector(item: dict, people: list[str]) -> list[str]:
    columns = st.columns(min(len(people), 4))
    selected = []
    saved_portions = st.session_state.current_assignments.get(item["id"], {})
    for index, person in enumerate(people):
        with columns[index % len(columns)]:
            checked = st.checkbox(
                person,
                value=person in saved_portions,
                key=f"assign-people-{item['id']}-{person}",
            )
            if checked:
                selected.append(person)
    return selected


def _portion_inputs(item: dict, selected_people: list[str]) -> dict[str, Decimal]:
    if not selected_people:
        return {}

    if len(selected_people) == 1:
        return {selected_people[0]: Decimal("1")}

    columns = st.columns(min(len(selected_people), 4))
    portions = {}
    for index, person in enumerate(selected_people):
        with columns[index % len(columns)]:
            portion = st.number_input(
                f"{person} portions",
                min_value=0.0,
                value=float(st.session_state.current_assignments.get(item["id"], {}).get(person, Decimal("1"))),
                step=1.0,
                format="%.1f",
                key=f"portion-{item['id']}-{person}",
            )
            if portion > 0:
                portions[person] = Decimal(str(portion))
    return portions


def _quick_assignment_box(receipt: dict, people: list[str]) -> None:
    with st.expander("Quick assign by item number", expanded=False):
        st.write("Use short lines like `1 Alice`, `2 Bob`, `3 all`, or `1,4 Alice and Bob`.")
        note = st.text_area(
            "Assignment note",
            height=110,
            placeholder="1 Alice\n2 Bob\n3 all",
            key="quick-assignment-note",
        )
        if st.button("Apply quick assignments", use_container_width=True):
            applied = _apply_quick_assignments(note, receipt, people)
            if applied:
                st.success(f"Applied {applied} item assignment(s).")
            else:
                st.warning("I could not match any item numbers. Try `1 Alice` or `2 all`.")


def _apply_quick_assignments(note: str, receipt: dict, people: list[str]) -> int:
    applied = 0
    item_by_number = {str(index): item for index, item in enumerate(receipt["items"], 1)}
    people_by_lower = {person.lower(): person for person in people}

    for line in note.splitlines():
        numbers = _extract_item_numbers(line, item_by_number)
        if not numbers:
            continue

        eaters = _extract_people(line, people, people_by_lower)
        if not eaters:
            continue

        for number in numbers:
            item = item_by_number[number]
            if eaters == ["All"]:
                st.session_state[f"assign-mode-{item['id']}"] = "All"
                for person in people:
                    st.session_state[f"assign-people-{item['id']}-{person}"] = False
                st.session_state.current_assignments[item["id"]] = {
                    person: Decimal("1")
                    for person in people
                }
            else:
                st.session_state[f"assign-mode-{item['id']}"] = "Choose people"
                for person in people:
                    st.session_state[f"assign-people-{item['id']}-{person}"] = person in eaters
                st.session_state.current_assignments[item["id"]] = {
                    person: Decimal("1")
                    for person in eaters
                }
            applied += 1

    return applied


def _extract_item_numbers(line: str, item_by_number: dict[str, dict]) -> list[str]:
    numbers = []
    for token in line.replace(":", " ").replace(",", " ").split():
        clean = token.strip("#.()[]")
        if clean in item_by_number:
            numbers.append(clean)
    return list(dict.fromkeys(numbers))


def _extract_people(line: str, people: list[str], people_by_lower: dict[str, str]) -> list[str]:
    lowered = line.lower()
    if any(word in lowered for word in ("all", "everyone", "everybody")):
        return ["All"]

    eaters = []
    normalized = lowered.replace("&", " ").replace(",", " ").replace(" and ", " ")
    tokens = [token.strip() for token in normalized.split() if token.strip()]
    for token in tokens:
        person = people_by_lower.get(token)
        if person:
            eaters.append(person)

    for person in people:
        if person.lower() in lowered and person not in eaters:
            eaters.append(person)

    return list(dict.fromkeys(eaters))


def _with_stable_item_ids(receipt: dict) -> dict:
    stable_items = []
    for index, item in enumerate(receipt["items"]):
        stable_items.append({**item, "id": f"item-{index}"})
    return {**receipt, "items": stable_items}


def _render_results(plan: dict, key_prefix: str = "result") -> None:
    st.subheader("Agent Split Result")

    total_paid = sum((split["total"] for split in plan["splits"]), Decimal("0"))
    summary_cols = st.columns(4)
    summary_cols[0].markdown(f"**Restaurant**  \n{plan['restaurant_name'] or 'Unknown'}")
    summary_cols[1].markdown(f"**Receipt total**  \n{money(plan['detected_total'])}")
    summary_cols[2].markdown(f"**Calculated total**  \n{money(plan.get('calculated_total', total_paid))}")
    summary_cols[3].markdown(f"**Assigned total**  \n{money(total_paid)}")

    for split in plan["splits"]:
        with st.container(border=True):
            st.markdown(f"**{split['person']}**")
            st.markdown(
                f"Total: **{money(split['total'])}**  \n"
                f"Items: {money(split['item_subtotal'])} | "
                f"Service: {money(split['service_charge'])} | "
                f"Tax: {money(split['tax'])}"
            )
            for item in split["items"]:
                portions = item.get("portions")
                portion_text = f" ({portions:g} portion)" if portions and portions != Decimal("1") else ""
                st.write(f"- {item['name']}: {money(item['amount'])}{portion_text}")

    st.text_area("Copy summary", value=_copyable_summary(plan), height=260, key=f"{key_prefix}-copy-summary")

    if plan.get("recommendations"):
        st.info(" ".join(plan["recommendations"]))


def _copyable_summary(plan: dict) -> str:
    lines = [
        f"Restaurant: {plan['restaurant_name'] or 'Unknown'}",
        f"Receipt total: {money(plan['detected_total'])}",
        f"Calculated total: {money(plan.get('calculated_total', plan['detected_total']))}",
        "",
        "Split:",
    ]
    for split in plan["splits"]:
        lines.append(f"{split['person']}: {money(split['total'])}")
        lines.append(
            f"  Items: {money(split['item_subtotal'])}, "
            f"Service: {money(split['service_charge'])}, "
            f"Tax: {money(split['tax'])}"
        )
        for item in split["items"]:
            portions = item.get("portions")
            portion_text = f" ({portions:g} portion)" if portions and portions != Decimal("1") else ""
            lines.append(f"  - {item['name']}: {money(item['amount'])}{portion_text}")
        lines.append("")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    main()
