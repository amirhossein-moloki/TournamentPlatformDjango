from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from django.db import models
from wallet.models import Transaction
from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from users.models import Team, User
from users.serializers import TeamSerializer
from .exceptions import ApplicationError
from .filters import TournamentFilter
from django_filters.rest_framework import DjangoFilterBackend
from verification.models import Verification

from .models import Game, Match, Tournament, Participant
from .serializers import (
    GameSerializer,
    MatchSerializer,
    TournamentSerializer,
    ParticipantSerializer,
)
from notifications.tasks import (
    send_email_notification,
    send_sms_notification,
)
from django.core.exceptions import PermissionDenied
from .services import (
    join_tournament,
    generate_matches,
    pay_prize,
    refund_entry_fees,
    get_tournament_winners,
)
from notifications.services import send_notification
from .models import Report, WinnerSubmission
from .serializers import ReportSerializer, WinnerSubmissionSerializer, ScoringSerializer
from .models import Scoring


class TournamentParticipantListView(generics.ListAPIView):
    """
    API view to list participants of a tournament.
    """

    serializer_class = ParticipantSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tournament_id = self.kwargs["pk"]
        return Participant.objects.filter(tournament_id=tournament_id)


class TournamentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing tournaments.
    """

    queryset = Tournament.objects.all()
    serializer_class = TournamentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = TournamentFilter

    def get_permissions(self):
        if self.action in ["create", "destroy"]:
            return [IsAdminUser()]
        return super().get_permissions()

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def join(self, request, pk=None):
        """
        Join a tournament.
        """
        tournament = self.get_object()
        user = request.user

        try:
            verification = user.verification
        except Verification.DoesNotExist:
            verification = None

        if verification is None or verification.level < tournament.required_verification_level:
            return Response({'error': 'You do not have the required verification level to join this tournament.'}, status=status.HTTP_403_FORBIDDEN)

        if user.score >= 1000 and (verification is None or verification.level < 2):
            return Response({'error': 'You must be verified at level 2 to join this tournament.'}, status=status.HTTP_403_FORBIDDEN)

        if user.score >= 2000 and (verification is None or verification.level < 3):
            return Response({'error': 'You must be verified at level 3 to join this tournament.'}, status=status.HTTP_403_FORBIDDEN)

        if tournament.type == "individual":
            try:
                participant = join_tournament(
                    tournament=tournament, user=user, team=None, members=None
                )
                serializer = ParticipantSerializer(participant)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except ApplicationError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        elif tournament.type == "team":
            team_id = request.data.get("team_id")
            member_ids = request.data.get("member_ids")

            if not team_id or not member_ids:
                return Response(
                    {"error": "Team ID and member IDs are required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                team = Team.objects.get(id=team_id)
                members = User.objects.filter(id__in=member_ids)
            except (Team.DoesNotExist, User.DoesNotExist):
                return Response(
                    {"error": "Invalid team or member ID."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if user != team.captain:
                return Response(
                    {"error": "Only the team captain can join a tournament."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if len(members) > 4:
                return Response(
                    {"error": "You can select a maximum of 4 members."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                team = join_tournament(
                    tournament=tournament, user=user, team=team, members=members
                )

                # Send notifications
                context = {
                    "tournament_name": tournament.name,
                    "entry_code": "placeholder-entry-code",  # Replace with actual entry code
                    "room_id": "placeholder-room-id",  # Replace with actual room ID
                }
                for member in members:
                    send_email_notification.delay(
                        member.email, "Tournament Joined", context
                    )
                    send_sms_notification.delay(str(member.phone_number), context)

                serializer = TeamSerializer(team)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            except ApplicationError as e:
                return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def generate_matches(self, request, pk=None):
        """
        Generate matches for a tournament.
        """
        tournament = self.get_object()
        try:
            generate_matches(tournament)
            return Response({"message": "Matches generated successfully."})
        except ValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def start_countdown(self, request, pk=None):
        """
        Start the countdown for a tournament.
        """
        tournament = self.get_object()
        tournament.countdown_start_time = timezone.now()
        tournament.save()
        send_tournament_credentials.apply_async(
            (tournament.id,), eta=tournament.countdown_start_time + timezone.timedelta(minutes=5)
        )
        return Response({"message": "Countdown started."})


class MatchViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing matches.
    """

    queryset = Match.objects.all()
    serializer_class = MatchSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action in ["create", "destroy"]:
            return [IsAdminUser()]
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def confirm_result(self, request, pk=None):
        """
        Confirm the result of a match.
        """
        match = self.get_object()
        user = request.user
        winner_id = request.data.get("winner_id")

        if not winner_id:
            return Response(
                {"error": "Winner ID not provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            confirm_match_result(match, user, winner_id)
            return Response({"message": "Match result confirmed successfully."})
        except (PermissionDenied, ValidationError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def dispute_result(self, request, pk=None):
        """
        Dispute the result of a match.
        """
        match = self.get_object()
        user = request.user
        reason = request.data.get("reason")

        if not reason:
            return Response(
                {"error": "Reason for dispute not provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            dispute_match_result(match, user, reason)
            return Response({"message": "Match result disputed successfully."})
        except (PermissionDenied, ValidationError) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class GameViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing games.
    """

    queryset = Game.objects.all()
    serializer_class = GameSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsAdminUser()]
        return super().get_permissions()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def private_media_view(request, path):
    """
    This view serves private media files. It requires authentication and
    checks if the user is a participant in the match to which the file
    belongs.
    """
    try:
        match = Match.objects.get(result_proof=f"private_result_proofs/{path}")
    except Match.DoesNotExist:
        raise Http404

    is_participant = False
    if match.match_type == "individual":
        if request.user in [match.participant1_user, match.participant2_user]:
            is_participant = True
    else:
        if request.user in [
            match.participant1_team.captain,
            match.participant2_team.captain,
        ] or request.user in match.participant1_team.members.all() or request.user in match.participant2_team.members.all():
            is_participant = True

    if is_participant or request.user.is_staff:
        file_path = f"{settings.PRIVATE_MEDIA_ROOT}/{path}"
        return FileResponse(open(file_path, "rb"))
    else:
        return Response(
            {"error": "You do not have permission to access this file."}, status=403
        )


class ReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing reports.
    """

    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Report.objects.all()
        return Report.objects.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        report = serializer.save(reporter=self.request.user)
        send_notification(
            user=report.reported_user,
            message=f"You have been reported in match {report.match}.",
            notification_type="report_new",
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def resolve(self, request, pk=None):
        """
        Resolve a report and ban the reported user if necessary.
        """
        report = self.get_object()
        ban_user = request.data.get("ban_user", False)
        if ban_user:
            reported_user = report.reported_user
            reported_user.is_active = False
            reported_user.save()
            report.status = "resolved"
            report.save()
            send_notification(
                user=report.reporter,
                message=f"Your report against {reported_user.username} has been resolved and the user has been banned.",
                notification_type="report_status_change",
            )
            return Response({"message": "Report resolved and user banned."})
        else:
            report.status = "resolved"
            report.save()
            send_notification(
                user=report.reporter,
                message=f"Your report against {report.reported_user.username} has been resolved.",
                notification_type="report_status_change",
            )
            return Response({"message": "Report resolved."})

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """
        Reject a report.
        """
        report = self.get_object()
        report.status = "rejected"
        report.save()
        send_notification(
            user=report.reporter,
            message=f"Your report against {report.reported_user.username} has been rejected.",
            notification_type="report_status_change",
        )
        return Response({"message": "Report rejected."})


class WinnerSubmissionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing winner submissions.
    """

    queryset = WinnerSubmission.objects.all()
    serializer_class = WinnerSubmissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return WinnerSubmission.objects.all()
        return WinnerSubmission.objects.filter(winner=self.request.user)

    def perform_create(self, serializer):
        # Check if the user is one of the top 5 winners
        winners = get_tournament_winners(serializer.validated_data["tournament"])
        if self.request.user not in winners:
            raise PermissionDenied("You are not one of the top 5 winners.")
        submission = serializer.save(winner=self.request.user)
        send_notification(
            user=self.request.user,
            message="Your winner submission has been received.",
            notification_type="winner_submission_status_change",
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def approve(self, request, pk=None):
        """
        Approve a winner submission and pay the prize.
        """
        submission = self.get_object()
        submission.status = "approved"
        submission.save()
        pay_prize(submission.tournament, submission.winner)
        send_notification(
            user=submission.winner,
            message=f"Your submission for {submission.tournament.name} has been approved.",
            notification_type="winner_submission_status_change",
        )
        return Response({"message": "Submission approved and prize paid."})

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def reject(self, request, pk=None):
        """
        Reject a winner submission.
        """
        submission = self.get_object()
        submission.status = "rejected"
        submission.save()
        refund_entry_fees(submission.tournament, submission.winner)
        send_notification(
            user=submission.winner,
            message=f"Your submission for {submission.tournament.name} has been rejected.",
            notification_type="winner_submission_status_change",
        )
        return Response({"message": "Submission rejected and entry fees refunded."})


class AdminReportListView(generics.ListAPIView):
    """
    API view for admin to see all reports.
    """

    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAdminUser]


class AdminWinnerSubmissionListView(generics.ListAPIView):
    """
    API view for admin to see all winner submissions.
    """

    queryset = WinnerSubmission.objects.all()
    serializer_class = WinnerSubmissionSerializer
    permission_classes = [IsAdminUser]


class ScoringViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing scores.
    """

    queryset = Scoring.objects.all()
    serializer_class = ScoringSerializer
    permission_classes = [IsAdminUser]


class TopTournamentsView(APIView):
    """
    API view for getting top tournaments by prize pool.
    """

    def get(self, request):
        past_tournaments = (
            Tournament.objects.filter(end_date__lt=timezone.now())
            .order_by("-entry_fee")
        )
        future_tournaments = (
            Tournament.objects.filter(start_date__gte=timezone.now())
            .order_by("-entry_fee")
        )

        past_serializer = TournamentSerializer(past_tournaments, many=True)
        future_serializer = TournamentSerializer(future_tournaments, many=True)

        return Response(
            {
                "past_tournaments": past_serializer.data,
                "future_tournaments": future_serializer.data,
            }
        )


class TotalPrizeMoneyView(APIView):
    """
    API view for getting the total prize money paid out.
    """

    def get(self, request):
        total_prize_money = (
            Transaction.objects.filter(transaction_type="prize").aggregate(
                total=models.Sum("amount")
            )["total"]
            or 0
        )
        return Response({"total_prize_money": total_prize_money})


class TotalTournamentsView(APIView):
    """
    API view for getting the total number of tournaments held.
    """

    def get(self, request):
        total_tournaments = Tournament.objects.count()
        return Response({"total_tournaments": total_tournaments})
