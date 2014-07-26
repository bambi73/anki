from __future__ import division
from aqt import reviewer
from anki import collection, sched, cards, find
from anki.utils import intTime, splitFields
from anki.hooks import runFilter, runHook
from anki.sound import stripSounds
from anki.consts import *
import anki.template
import re

from aqt.utils import showWarning

##########################################################################

_CARD_FLAG__WARNING_1 = 1 << 16
_CARD_FLAG__WARNING_2 = 1 << 17
_CARD_FLAG__WARNING_3 = 1 << 18

_CARD_FLAG__LIMIT_WARNING = _CARD_FLAG__WARNING_2

##########################################################################

def myKeyHandler(self, evt):
    key = unicode(evt.text())
    if key == "5":
        self._answerCard(int(key))
    else:
        origKeyHandler(self, evt)

origKeyHandler = reviewer.Reviewer._keyHandler 
reviewer.Reviewer._keyHandler = myKeyHandler


def myDefaultEase(self):
    if self.mw.col.sched.answerButtons(self.card) == 5:
        return 4
    else:
        return origDefaultEase(self)

origDefaultEase = reviewer.Reviewer._defaultEase 
reviewer.Reviewer._defaultEase = myDefaultEase


def myAnswerButtonList(self):
    count = self.mw.col.sched.answerButtons(self.card)
    if count == 5:
        return ((1, _("Again")), (2, "Shaky"), (3, _("Hard")), (4, _("Good")), (5, _("Easy")))
    else:
        return origAnswerButtonList(self)
  
origAnswerButtonList = reviewer.Reviewer._answerButtonList 
reviewer.Reviewer._answerButtonList = myAnswerButtonList

    
def myAnswerButtons(self, card):
    count = origAnswerButtons(self, card)
    if count == 4:
        return 5
    else:
        return count

origAnswerButtons = sched.Scheduler.answerButtons 
sched.Scheduler.answerButtons = myAnswerButtons


def myNextRevIvl(self, card, ease):
    "Ideal next interval for CARD, given EASE."
    delay = self._daysLate(card)
    conf = self._revConf(card)
    fct = card.factor / 1000
    ivl2 = self._constrainedIvl((card.ivl + delay // 4) * 1.2, conf, card.ivl)
    ivl3 = self._constrainedIvl((card.ivl + delay // 2) * fct, conf, ivl2)
    ivl4 = self._constrainedIvl((card.ivl + delay) * fct * conf['ease4'], conf, ivl3)
    ivlShaky = (card.ivl + 1) // 2
    if ivlShaky <= 0:
        ivlShaky = 1
#    self.col.log("ease=%d, delay=%d, fct=%f, ivlShaky=%d, ivl2=%d, ivl3=%d, ivl4=%d, conf=%s" % (ease, delay, fct, ivlShaky, ivl2, ivl3, ivl4, conf))
    if _isShakyMode(self, card):
        if ease == 2:
            interval = ivlShaky
        elif ease == 3:
            interval = ivl2
        elif ease == 4:
            interval = ivl3
        elif ease == 5:
            interval = ivl4
    else:
        if ease == 2:
            interval = ivl2
        elif ease == 3:
            interval = ivl3
        elif ease == 4:
            interval = ivl4
    # interval capped?
    return min(interval, conf['maxIvl'])

sched.Scheduler._nextRevIvl = myNextRevIvl


def myAnswerCard(self, card, ease):
    self.col.log()
    assert ease >= 1 and ease <= 5
    self.col.markReview(card)
    if self._burySiblingsOnAnswer:
        self._burySiblings(card)
    card.reps += 1
    # former is for logging new cards, latter also covers filt. decks
    card.wasNew = card.type == 0
    wasNewQ = card.queue == 0
    if wasNewQ:
        # came from the new queue, move to learning
        card.queue = 1
        # if it was a new card, it's now a learning card
        if card.type == 0:
            card.type = 1
        # init reps to graduation
        card.left = self._startingLeft(card)
        # dynamic?
        if card.odid and card.type == 2:
            if self._resched(card):
                # reviews get their ivl boosted on first sight
                card.ivl = self._dynIvlBoost(card)
                card.odue = self.today + card.ivl
        self._updateStats(card, 'new')
    if card.queue in (1, 3):
        self._answerLrnCard(card, ease)
        if not wasNewQ:
            self._updateStats(card, 'lrn')
    elif card.queue == 2:
        self._answerRevCard(card, ease)
        self._updateStats(card, 'rev')
    else:
        raise Exception("Invalid queue")
    self._updateStats(card, 'time', card.timeTaken())
    card.mod = intTime()
    card.usn = self.col.usn()
    card.flushSched()

sched.Scheduler.answerCard = myAnswerCard


def _isShakyMode(shed, card):
    return shed.answerButtons(card) == 5


def _isShakyButton(shed, card, ease):
    return _isShakyMode(shed, card) and ease == 2


def _isShakyLapse(shed, card, ease):
    return _isShakyButton(shed, card, ease) and (card.flags & _CARD_FLAG__LIMIT_WARNING)


def _resetShaky(shed, card):
    if card.flags & _CARD_FLAG__WARNING_1:
        card.flags ^= _CARD_FLAG__WARNING_1
    if card.flags & _CARD_FLAG__WARNING_2:
        card.flags ^= _CARD_FLAG__WARNING_2
    if card.flags & _CARD_FLAG__WARNING_3:
        card.flags ^= _CARD_FLAG__WARNING_3


def _shiftShaky(shed, card):
    origCardFlags = card.flags
    assert not origCardFlags & _CARD_FLAG__LIMIT_WARNING
    _resetShaky(shed, card)
    if origCardFlags & _CARD_FLAG__WARNING_2:
        card.flags |= _CARD_FLAG__WARNING_3
    elif origCardFlags & _CARD_FLAG__WARNING_1:
        card.flags |= _CARD_FLAG__WARNING_2
    else:
        card.flags |= _CARD_FLAG__WARNING_1


def myAnswerRevCard(self, card, ease):
    delay = 0
    if ease == 1 or _isShakyLapse(self, card, ease):
        if _isShakyMode(self, card):
            _resetShaky(self, card)
        delay = self._rescheduleLapse(card)
        self._logRev(card, 1, delay)
    else:
        if _isShakyButton(self, card, ease):
            _shiftShaky(self, card)
        elif _isShakyMode(self, card):
            _resetShaky(self, card)
        self._rescheduleRev(card, ease)
        if _isShakyMode(self, card) and ease > 2:
            self._logRev(card, ease - 1, delay)
        else:
            self._logRev(card, ease, delay)

sched.Scheduler._answerRevCard = myAnswerRevCard


def myRescheduleRev(self, card, ease):
    # update interval
    card.lastIvl = card.ivl
    if self._resched(card):
        self._updateRevIvl(card, ease)
        # then the rest
        if _isShakyMode(self, card):
            card.factor = max(1300, card.factor+[-150, -150, 0, 150][ease-2])
        else:
            card.factor = max(1300, card.factor+[-150, 0, 150][ease-2])
        card.due = self.today + card.ivl
    else:
        card.due = card.odue
    if card.odid:
        card.did = card.odid
        card.odid = 0
        card.odue = 0

sched.Scheduler._rescheduleRev = myRescheduleRev


def myNextIvl(self, card, ease):
    "Return the next interval for CARD, in seconds."
    if card.queue in (0,1,3):
        return self._nextLrnIvl(card, ease)
    elif ease == 1 or _isShakyLapse(self, card, ease):
        # lapsed
        conf = self._lapseConf(card)
        if conf['delays']:
            return conf['delays'][0]*60
        return self._nextLapseIvl(card, conf)*86400
    else:
        # review
        return self._nextRevIvl(card, ease)*86400

sched.Scheduler.nextIvl = myNextIvl


def myFlushSched(self):
    self.mod = intTime()
    self.usn = self.col.usn()
    # bug checks
    if self.queue == 2 and self.odue and not self.col.decks.isDyn(self.did):
        runHook("odueInvalid")
    assert self.due < 4294967296
    self.col.db.execute(
        """update cards set
mod=?, usn=?, type=?, queue=?, due=?, ivl=?, factor=?, reps=?,
lapses=?, left=?, odue=?, odid=?, did=?, flags=? where id = ?""",
        self.mod, self.usn, self.type, self.queue, self.due, self.ivl,
        self.factor, self.reps, self.lapses,
        self.left, self.odue, self.odid, self.did, self.flags, self.id)
    self.col.log(self)

cards.Card.flushSched = myFlushSched


def myGetQA(self, reload=False, browser=False):
    if not self._qa or reload:
        f = self.note(reload); m = self.model(); t = self.template()
        data = [self.id, f.id, m['id'], self.odid or self.did, self.ord,
                f.stringTags(), f.joinedFields(), self.flags]
        if browser:
            args = (t.get('bqfmt'), t.get('bafmt'))
        else:
            args = tuple()
        self._qa = self.col._renderQA(data, *args)
    return self._qa

cards.Card._getQA = myGetQA


def _getShakyWarningFieldName(flags):
    if flags:
        if flags & _CARD_FLAG__WARNING_3:
            return "ShakyWarning3"
        if flags & _CARD_FLAG__WARNING_2:
            return "ShakyWarning2"
        if flags & _CARD_FLAG__WARNING_1:
            return "ShakyWarning1"
    return None


def myRenderQA(self, data, qfmt=None, afmt=None):
    "Returns hash of id, question, answer."
    # data is [cid, nid, mid, did, ord, tags, flds, flags]
    # unpack fields and create dict
    flist = splitFields(data[6])
    fields = {}
    model = self.models.get(data[2])
    for (name, (idx, conf)) in self.models.fieldMap(model).items():
        fields[name] = flist[idx]
    if len(data) > 7:
        shakyWarningFieldName = _getShakyWarningFieldName(data[7])
        if shakyWarningFieldName:
            fields[shakyWarningFieldName] = shakyWarningFieldName
    fields['Tags'] = data[5].strip()
    fields['Type'] = model['name']
    fields['Deck'] = self.decks.name(data[3])
    if model['type'] == MODEL_STD:
        template = model['tmpls'][data[4]]
    else:
        template = model['tmpls'][0]
    fields['Card'] = template['name']
    fields['c%d' % (data[4]+1)] = "1"
    # render q & a
    d = dict(id=data[0])
    qfmt = qfmt or template['qfmt']
    afmt = afmt or template['afmt']
    for (type, format) in (("q", qfmt), ("a", afmt)):
        if type == "q":
            format = re.sub("{{(?!type:)(.*?)cloze:", r"{{\1cq-%d:" % (data[4]+1), format)
            format = format.replace("<%cloze:", "<%%cq:%d:" % (
                data[4]+1))
        else:
            format = re.sub("{{(.*?)cloze:", r"{{\1ca-%d:" % (data[4]+1), format)
            format = format.replace("<%cloze:", "<%%ca:%d:" % (
                data[4]+1))
            fields['FrontSide'] = stripSounds(d['q'])
        fields = runFilter("mungeFields", fields, model, data, self)
        html = anki.template.render(format, fields)
        d[type] = runFilter(
            "mungeQA", html, type, fields, model, data, self)
        # empty cloze?
        if type == 'q' and model['type'] == MODEL_CLOZE:
            if not self.models._availClozeOrds(model, data[6], False):
                d['q'] += ("<p>" + _(
            "Please edit this note and add some cloze deletions. (%s)") % (
            "<a href=%s#cloze>%s</a>" % (HELP_SITE, _("help"))))
    return d

collection._Collection._renderQA = myRenderQA


def myQAData(self, where=""):
    "Return [cid, nid, mid, did, ord, tags, flds, flags] db query"
    return self.db.execute("""
select c.id, f.id, f.mid, c.did, c.ord, f.tags, f.flds, c.flags
from cards c, notes f
where c.nid == f.id
%s""" % where)

collection._Collection._qaData = myQAData


def myFindCardState(self, (val, args)):
    if val == "shaky":
        return "((c.flags & %d) != 0 or (c.flags & %d) != 0 or (c.flags & %d) != 0)" % (_CARD_FLAG__WARNING_1, _CARD_FLAG__WARNING_2, _CARD_FLAG__WARNING_3)
    else:
        return origFindCardState(self, (val, args))

origFindCardState = find.Finder._findCardState 
find.Finder._findCardState  = myFindCardState


