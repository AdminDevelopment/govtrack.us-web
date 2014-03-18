"""
Parse list of committees which ever were in Congress.
Parse members of current congress committees.
"""
from lxml import etree
from datetime import datetime
import logging

from django.conf import settings

from parser.progress import Progress
from parser.processor import YamlProcessor, yaml_load
from parser.models import File
from committee.models import (Committee, CommitteeType, CommitteeMember,
                              CommitteeMemberRole, CommitteeMeeting)
from person.models import Person
from bill.models import Bill, BillType

import json, re
import common.enum

log = logging.getLogger('parser.committee_parser')

TYPE_MAPPING = {'senate': CommitteeType.senate,
                'joint': CommitteeType.joint,
                'house': CommitteeType.house}

ROLE_MAPPING = {
    'Ex Officio': CommitteeMemberRole.exofficio,
    'Chairman': CommitteeMemberRole.chairman,
    'Cochairman': CommitteeMemberRole.chairman, # huh!
    'Co-Chairman': CommitteeMemberRole.chairman, # huh!
    'Chair': CommitteeMemberRole.chairman,
    'Ranking Member': CommitteeMemberRole.ranking_member,
    'Vice Chairman': CommitteeMemberRole.vice_chairman,
    'Vice Chair': CommitteeMemberRole.vice_chairman,
    'Vice Chairwoman': CommitteeMemberRole.vice_chairman,
    'Member': CommitteeMemberRole.member,
}

class CommitteeMeetingProcessor(YamlProcessor):
    """
    Parser of committee meeting JSON files.
    """

    REQUIRED_ATTRIBUTES = [ "guid", "congress", "committee", "occurs_at", "topic" ]
    ATTRIBUTES = [ "guid", "house_event_id", "house_meeting_type", "congress", "chamber", "committee", "subcommittee", "occurs_at", "room", "topic", "closed", "bills" ]
    FIELD_MAPPING = { "house_event_id": "event_id", "house_meeting_type": "meeting_type" }

    def committee_handler(self, value):
        return Committee.objects.get(code=value)

    def occurs_at_handler(self, value):
        return self.parse_datetime(value)


def main(options):
    """
    Process committees, subcommittees and
    members of current congress committees.
    """

    BASE_PATH = settings.CONGRESS_LEGISLATORS_PATH

    meeting_processor = CommitteeMeetingProcessor()

    log.info('Processing committees')
    COMMITTEES_FILE = BASE_PATH + 'committees-current.yaml'

    if not File.objects.is_changed(COMMITTEES_FILE) and not options.force:
        log.info('File %s was not changed' % COMMITTEES_FILE)
    else:
        tree = yaml_load(COMMITTEES_FILE)
        total = len(tree)
        progress = Progress(total=total)
        seen_committees = set()
        for committee in tree:
            try:
                cobj = Committee.objects.get(code=committee["thomas_id"])
            except Committee.DoesNotExist:
                print "New committee:", committee["thomas_id"]
                cobj = Committee(code=committee["thomas_id"])

            cobj.committee_type = TYPE_MAPPING[committee["type"]]
            cobj.name = committee["name"]
            cobj.url = committee.get("url", None)
            cobj.obsolete = False
            cobj.committee = None
            cobj.save()
            seen_committees.add(cobj.id)

            for subcom in committee.get('subcommittees', []):
                code = committee["thomas_id"] + subcom["thomas_id"]
                try:
                    sobj = Committee.objects.get(code=code)
                except Committee.DoesNotExist:
                    print "New subcommittee:", code
                    sobj = Committee(code=code)

                sobj.name = subcom["name"]
                sobj.url = subcom.get("url", None)
                sobj.type = None
                sobj.committee = cobj
                sobj.obsolete = False
                sobj.save()
                seen_committees.add(sobj.id)

            progress.tick()

        # Check for non-obsolete committees in the database that aren't in our
        # file.
        other_committees = Committee.objects.filter(obsolete=False).exclude(id__in=seen_committees)
        if len(other_committees) > 0:
            print "Marking obsolete:", ", ".join(c.code for c in other_committees)
            other_committees.update(obsolete=True)

        File.objects.save_file(COMMITTEES_FILE)

    log.info('Processing committee members')
    MEMBERS_FILE = BASE_PATH + 'committee-membership-current.yaml'
    file_changed = File.objects.is_changed(MEMBERS_FILE)

    if not file_changed and not options.force:
        log.info('File %s was not changed' % MEMBERS_FILE)
    else:
        # map THOMAS IDs to GovTrack IDs
        y = yaml_load(BASE_PATH + "legislators-current.yaml")
        person_id_map = { }
        for m in y:
            if "id" in m and "govtrack" in m["id"] and "thomas" in m["id"]:
                person_id_map[m["id"]["thomas"]] = m["id"]["govtrack"]

        # load committee members
        tree = yaml_load(MEMBERS_FILE)
        total = len(tree)
        progress = Progress(total=total, name='committees')

        # We can delete CommitteeMember objects because we don't have
        # any foreign keys to them.
        CommitteeMember.objects.all().delete()

        # Process committee nodes
        for committee, members in tree.items():
            try:
                cobj = Committee.objects.get(code=committee)
            except Committee.DoesNotExist:
                print "Committee not found:", committee
                continue

            # Process members of current committee node
            for member in members:
                # Ignore missing members, as they've probably retired.
                if "thomas" in member and member["thomas"] in person_id_map:
                    mobj = CommitteeMember()
                    mobj.person = Person.objects.get(id=person_id_map[member["thomas"]])
                    mobj.committee = cobj
                    if "title" in member:
                        mobj.role = ROLE_MAPPING[member["title"]]
                    mobj.save()

            progress.tick()

        File.objects.save_file(MEMBERS_FILE)

    log.info('Processing committee schedule')
    for chamber in ("house", "senate"):
		meetings_file = 'data/congress/committee_meetings_%s.json' % chamber
		file_changed = File.objects.is_changed(meetings_file)

		if not file_changed and not options.force:
			log.info('File %s was not changed' % meetings_file)
		else:
			meetings = json.load(open(meetings_file))

			# Process committee event nodes
			for meeting in meetings:
				try:
					mobj = meeting_processor.process(CommitteeMeeting(), meeting)

					# Associate it with an existing meeting object if GUID is already known.
					try:
						mobj.id = CommitteeMeeting.objects.get(guid=mobj.guid).id
					except CommitteeMeeting.DoesNotExist:
						pass

					# Attach the meeting to the subcommittee if set.
					if mobj.subcommittee:
						mobj.committee = Committee.objects.get(code=mobj.committee.code + mobj.subcommittee)

					# XXX: This is a hack.
					if "closed hearings" in mobj.topic.lower():
						mobj.closed = True

					if mobj.created is None:
						mobj.created = datetime.now()

					mobj.save()

					mobj.bills.clear()
					for bill in meeting["bills"]:
						try:
							bill_type, bill_num, bill_cong = re.match(r"([a-z]+)(\d+)-(\d+)$", bill).groups()
							bill_obj = Bill.objects.get(congress=bill_cong, bill_type=BillType.by_slug(bill_type), number=int(bill_num))
							print bill, bill_obj
							mobj.bills.add(bill_obj)
						except AttributeError as e:
							print "bill: AttributeError", e, bill
							pass # regex failed
						except common.enum.NotFound as e:
							print "bill: NotFound", e, bill
							pass # invalid bill type code in source data
						except Bill.DoesNotExist:
							pass # we don't know about bill yet
					print mobj.bills
				except Committee.DoesNotExist:
					log.error('Could not load Committee object for meeting %s' % meeting_processor.display_node(meeting))

			for committee in Committee.objects.all():
				if not options.disable_events:
					committee.create_events()

			File.objects.save_file(meetings_file)


if __name__ == '__main__':
    main()
