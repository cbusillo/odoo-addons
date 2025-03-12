import logging
import traceback

from odoo import api, models, fields

_logger = logging.getLogger(__name__)


class NotificationHistory(models.Model):
    _name = "notification.history"
    _description = "Notification History"

    subject = fields.Char()
    timestamp = fields.Datetime(default=fields.Datetime.now)
    channel_name = fields.Char()

    @api.model
    def cleanup(self) -> None:
        one_week_ago = fields.Datetime.subtract(fields.Datetime.now(), weeks=1)
        self.search([("timestamp", "<", one_week_ago)]).unlink()

    @api.model
    def count_of_recent_notifications(self, subject: str, channel_name: str, hours: int) -> int:
        return len(self.recent_notifications(subject, channel_name, hours))

    @api.model
    def recent_notifications(self, subject: str, channel_name: str, hours: int) -> "NotificationHistory":
        time_frame = fields.Datetime.subtract(fields.Datetime.now(), hours=hours)
        return self.search(
            [("timestamp", ">=", time_frame), ("subject", "=", subject), ("channel_name", "=", channel_name)]
        )


class NotificationManagerMixin(models.AbstractModel):
    _name = "notification.manager.mixin"
    _description = "Notification Manager Mixin"

    ADMIN_EMAIL = "info@shinycomputers.com"

    def notify_channel(
        self,
        subject: str,
        body: str,
        channel_name: str,
        record: models.Model | None = None,
        env: api.Environment | None = None,
        error_traceback: str | None = None,
    ) -> None:
        env = env or self.env
        notification_history = env["notification.history"]
        if notification_history.count_of_recent_notifications(subject, channel_name, 1) > 5:
            _logger.info(f"Too many notifications for {subject} in the last hour.")
            return

        channel = env["discuss.channel"].search([("name", "=", channel_name)], limit=1)
        if not channel:
            channel = env["discuss.channel"].create({"name": channel_name})

        if error_traceback:
            body += "\n\nError traceback:\n"
            body += error_traceback

        _logger.debug(
            "Sending message to channel %s with message %s for record %s",
            channel,
            body,
            record,
        )

        if record:
            record.message_post(body=body, subject=subject, message_type="auto_comment")
        else:
            channel.message_post(body=body, subject=subject, message_type="auto_comment")

        notification_history.create({"subject": subject, "channel_name": channel_name})
        notification_history.cleanup()

    def notify_channel_on_error(
        self,
        subject: str,
        body: str,
        record: models.Model | None = None,
        error: Exception | None = None,
    ) -> None:
        error_traceback = None
        if error:
            error_traceback = "".join(traceback.format_exception(type(error), error, error.__traceback__))

        new_cr = self.env.registry.cursor()
        try:
            new_env = api.Environment(new_cr, self.env.uid, self.env.context)
            self.notify_channel(subject, body, "errors", record, new_env, error_traceback)
            self.send_email_notification_to_admin(subject, body + "\n\n" + error_traceback)
            new_cr.commit()
        finally:
            new_cr.close()

    def send_email_notification_to_admin(self, subject: str, body: str) -> None:
        recipient_user = self.env["res.users"].search([("login", "=", self.ADMIN_EMAIL)], limit=1)
        if not recipient_user:
            _logger.error("Recipient email %s not found among partners.", self.ADMIN_EMAIL)
            return

        # Create an email and send it
        mail_values = {
            "subject": subject,
            "body_html": f"<div>{body}</div>",
            "recipient_ids": [(4, recipient_user.id)],
            "email_from": self.env["ir.mail_server"].sudo().search([], limit=1).smtp_user,
        }
        mail = self.env["mail.mail"].sudo().create(mail_values)
        mail.send()
